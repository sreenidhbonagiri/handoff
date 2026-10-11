import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import Dashboard from "./components/Dashboard";
import JobWorkspace from "./components/JobWorkspace";
import Landing from "./components/Landing";
import { clearDrafts, confirmLeaveJob, hasUnsavedDrafts } from "./drafts";
import { dashboardPath, jobPath, landingPath, parseRoute, type Route } from "./route";
import type { Health, JobListItem, JobState } from "./types";

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute());
  const [job, setJob] = useState<JobState | null>(null);
  const [jobs, setJobs] = useState<JobListItem[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const wantedId = useRef<number | null>(route.name === "job" ? route.id : null);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(`Backend not reachable: ${e.message}`));
  }, []);

  const showLanding = useCallback((replace = false) => {
    wantedId.current = null;
    clearDrafts();
    setJob(null);
    setRoute({ name: "landing" });
    const path = landingPath();
    if (replace) window.history.replaceState({ name: "landing" }, "", path);
    else window.history.pushState({ name: "landing" }, "", path);
  }, []);

  const showDashboard = useCallback((replace = false) => {
    wantedId.current = null;
    clearDrafts();
    setJob(null);
    setRoute({ name: "dashboard" });
    const path = dashboardPath();
    if (replace) window.history.replaceState({ name: "dashboard" }, "", path);
    else window.history.pushState({ name: "dashboard" }, "", path);
  }, []);

  useEffect(() => {
    if (route.name === "landing") document.title = "Handoff";
    else if (route.name === "dashboard") document.title = "Jobs · Handoff";
    else document.title = `Job ${route.id} · Handoff`;
  }, [route]);

  const loadJob = useCallback(async (id: number, replace = false) => {
    wantedId.current = id;
    setError(null);
    setRoute({ name: "job", id });
    const path = jobPath(id);
    if (replace) window.history.replaceState({ name: "job", id }, "", path);
    else if (window.location.pathname !== path) window.history.pushState({ name: "job", id }, "", path);
    try {
      const next = await api.getJob(id);
      if (wantedId.current !== id) return;
      setJob(next);
    } catch (e) {
      if (wantedId.current !== id) return;
      setJob(null);
      setError(e instanceof Error ? e.message : String(e));
      showDashboard(true);
    }
  }, [showDashboard]);

  const refreshList = useCallback(async () => {
    try {
      setJobs(await api.listJobs());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (route.name === "dashboard") void refreshList();
  }, [route, refreshList]);

  useEffect(() => {
    if (route.name === "job") void loadJob(route.id, true);
    // Initial load from the current URL only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onPop = () => {
      if (hasUnsavedDrafts() && !confirmLeaveJob()) {
        if (wantedId.current) window.history.pushState({ name: "job", id: wantedId.current }, "", jobPath(wantedId.current));
        return;
      }
      clearDrafts();
      const next = parseRoute();
      setRoute(next);
      if (next.name === "job") void loadJob(next.id, true);
      else {
        wantedId.current = null;
        setJob(null);
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [loadJob]);

  useEffect(() => {
    const onBefore = (e: BeforeUnloadEvent) => {
      if (!hasUnsavedDrafts()) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBefore);
    return () => window.removeEventListener("beforeunload", onBefore);
  }, []);

  const leaveJob = () => {
    if (!confirmLeaveJob()) return;
    showDashboard();
  };

  const openJob = (id: number) => {
    void loadJob(id);
  };

  const createJob = async (title: string, location: string) => {
    if (creating) return;
    setCreating(true);
    setError(null);
    try {
      const next = await api.createJob(title, location);
      wantedId.current = next.job.id;
      setJob(next);
      setRoute({ name: "job", id: next.job.id });
      window.history.pushState({ name: "job", id: next.job.id }, "", jobPath(next.job.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  if (route.name === "landing") {
    return <Landing onOpenWorkspace={() => showDashboard()} />;
  }

  if (route.name === "job") {
    if (!job || job.job.id !== route.id) {
      return <div className="loading">{error ?? "Loading…"}</div>;
    }
    return (
      <JobWorkspace
        job={job}
        health={health}
        onJob={(next) => {
          if (wantedId.current === next.job.id) setJob(next);
        }}
        onAllJobs={leaveJob}
      />
    );
  }

  if (!jobs) {
    return <div className="loading">{error ?? "Loading…"}</div>;
  }

  return (
    <div className="app">
      {error && (
        <div className="error" role="alert">
          {error}
          <button className="link" type="button" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}
      <Dashboard
        items={jobs}
        onOpen={openJob}
        onCreate={(title, location) => void createJob(title, location)}
        onHome={() => showLanding()}
        creating={creating}
      />
    </div>
  );
}
