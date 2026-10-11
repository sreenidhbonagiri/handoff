import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { setDraftDirty } from "../drafts";
import { equipmentLine, hasJobNotes, jobTitle } from "../format";
import type { AskItem, FactState, Health, JobState, ObservationIn } from "../types";
import { IconBot, IconClipboardCheck } from "../icons";
import AppNav from "./AppNav";
import AskPanel from "./AskPanel";
import BrandLogo from "./BrandLogo";
import CloseoutPanel from "./CloseoutPanel";
import FactsPanel from "./FactsPanel";
import FollowUpPanel from "./FollowUpPanel";
import ReportPanel from "./ReportPanel";
import SourcePanel from "./SourcePanel";

const UPDATING = "Updating your job\u2026";

interface Props {
  job: JobState;
  health: Health | null;
  onJob: (next: JobState) => void;
  onAllJobs: () => void;
  onMap: () => void;
  onHome: () => void;
}

export default function JobWorkspace(props: Props) {
  const { job, health } = props;
  const jobId = job.job.id;
  const [selectedFactId, setSelectedFactId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flashIds, setFlashIds] = useState<Set<number>>(new Set());
  const [closeoutOpen, setCloseoutOpen] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const [title, setTitle] = useState(job.job.title);
  const [location, setLocation] = useState(job.job.location ?? "");
  const knownFactIds = useRef<Set<number>>(new Set(job.facts.map((f) => f.id)));
  const reviewButton = useRef<HTMLButtonElement>(null);
  const inFlight = useRef(false);
  const wantedId = useRef(jobId);
  const metaTimer = useRef<number | null>(null);
  wantedId.current = jobId;

  useEffect(() => {
    knownFactIds.current = new Set(job.facts.map((f) => f.id));
    inFlight.current = false;
    setSelectedFactId(null);
    setCloseoutOpen(false);
    setAskOpen(false);
    setTitle(job.job.title);
    setLocation(job.job.location ?? "");
    setError(null);
  }, [jobId]);

  useEffect(() => {
    setTitle(job.job.title);
    setLocation(job.job.location ?? "");
  }, [job.job.title, job.job.location]);

  const applyState = useCallback(
    (next: JobState) => {
      if (next.job.id !== wantedId.current) return false;
      const fresh = next.facts.filter((f) => !knownFactIds.current.has(f.id)).map((f) => f.id);
      knownFactIds.current = new Set(next.facts.map((f) => f.id));
      setFlashIds(new Set(fresh));
      props.onJob(next);
      return true;
    },
    [props],
  );

  const run = useCallback(
    async (label: string, action: () => Promise<JobState>): Promise<boolean> => {
      if (inFlight.current) return false;
      inFlight.current = true;
      const forJob = jobId;
      setBusy(label);
      setError(null);
      try {
        const next = await action();
        if (wantedId.current !== forJob) return false;
        applyState(next);
        return true;
      } catch (e) {
        if (wantedId.current !== forJob) return false;
        setError(e instanceof Error ? e.message : String(e));
        api
          .getJob(forJob)
          .then((latest) => {
            if (wantedId.current === forJob) applyState(latest);
          })
          .catch(() => undefined);
        return false;
      } finally {
        if (wantedId.current === forJob) {
          inFlight.current = false;
          setBusy(null);
        } else {
          inFlight.current = false;
        }
      }
    },
    [applyState, jobId],
  );

  const submit = (obs: ObservationIn) => run(UPDATING, () => api.addObservation(jobId, obs));

  const saveMeta = async (nextTitle: string, nextLocation: string) => {
    const titleChanged = nextTitle.trim() !== (job.job.title ?? "").trim();
    const locationChanged = nextLocation.trim() !== (job.job.location ?? "").trim();
    if (!titleChanged && !locationChanged) {
      setDraftDirty("job-meta", false);
      return true;
    }
    const ok = await run("Saving job details…", () =>
      api.updateJob(jobId, {
        ...(titleChanged ? { title: nextTitle } : {}),
        ...(locationChanged ? { location: nextLocation } : {}),
      }),
    );
    if (ok) setDraftDirty("job-meta", false);
    return ok;
  };

  const scheduleMeta = (nextTitle: string, nextLocation: string) => {
    setDraftDirty("job-meta", true);
    if (metaTimer.current) window.clearTimeout(metaTimer.current);
    metaTimer.current = window.setTimeout(() => {
      metaTimer.current = null;
      void saveMeta(nextTitle, nextLocation);
    }, 400);
  };

  useEffect(
    () => () => {
      if (metaTimer.current) window.clearTimeout(metaTimer.current);
    },
    [],
  );

  const voiceAvailable = !!health?.whisper_available && !!health.ffmpeg_available;
  const voiceUnavailableReason = !health
    ? "Checking local transcription…"
    : !health.ffmpeg_available
      ? "ffmpeg is not installed"
      : !health.whisper_available
        ? `whisper.cpp or the ${health.whisper_model} model is not installed`
        : null;

  const closeReview = () => {
    setCloseoutOpen(false);
    window.setTimeout(() => reviewButton.current?.focus(), 0);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-main">
          <a
            className="logo-link"
            href="/"
            aria-label="Handoff home"
            onClick={(e) => {
              e.preventDefault();
              props.onHome();
            }}
          >
            <BrandLogo size="app" />
          </a>
          <div className="topbar-tools">
            {busy && (
              <span className="busy" role="status" aria-live="polite">
                {busy}
              </span>
            )}
            <AppNav current="jobs" onHome={props.onHome} onJobs={props.onAllJobs} onMap={props.onMap} />
            <div className="topbar-actions">
              <button type="button" className="btn btn-assistant" onClick={() => setAskOpen(true)}>
                <IconBot />
                Ask Handoff
                <span className="ai-badge">AI</span>
              </button>
              <button
                ref={reviewButton}
                className="btn btn-primary"
                type="button"
                onClick={() => setCloseoutOpen(true)}
              >
                <IconClipboardCheck />
                Review before leaving
              </button>
            </div>
          </div>
        </div>
        <div className="job-identity">
          <h1>Job {jobId}</h1>
          <p className="asset-line">
            {jobTitle(job.job.title)}
            {" · "}
            {equipmentLine(job)}
          </p>
          <div className="job-fields compact">
            <label>
              <span className="muted small">Title</span>
              <input
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  scheduleMeta(e.target.value, location);
                }}
                onBlur={() => {
                  if (metaTimer.current) {
                    window.clearTimeout(metaTimer.current);
                    metaTimer.current = null;
                  }
                  void saveMeta(title, location);
                }}
                placeholder="Untitled service visit"
                maxLength={200}
              />
            </label>
            <label>
              <span className="muted small">Location</span>
              <input
                value={location}
                onChange={(e) => {
                  setLocation(e.target.value);
                  scheduleMeta(title, e.target.value);
                }}
                onBlur={() => {
                  if (metaTimer.current) {
                    window.clearTimeout(metaTimer.current);
                    metaTimer.current = null;
                  }
                  void saveMeta(title, location);
                }}
                placeholder="Location not added"
                maxLength={200}
              />
            </label>
          </div>
        </div>
      </header>
      {error && (
        <div className="error" role="alert">
          {error}
          <button className="link" type="button" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}
      <main className={`workspace${job.next_question && hasJobNotes(job) ? " has-follow" : ""}`}>
        <SourcePanel
          key={`note-${jobId}`}
          variant="composer"
          job={job}
          selectedFactId={selectedFactId}
          onSelectFact={setSelectedFactId}
          onSubmit={submit}
          onAddPhoto={(file, caption) => run(UPDATING, () => api.addPhoto(jobId, file, caption))}
          onEdit={(sourceId, text) => run(UPDATING, () => api.editSource(sourceId, text))}
          onRetry={(sourceId) => run(UPDATING, () => api.retrySource(sourceId))}
          onDraftChange={(dirty) => setDraftDirty("note", dirty)}
          busy={!!busy}
          voiceAvailable={voiceAvailable}
          voiceUnavailableReason={voiceUnavailableReason}
        />
        {job.next_question && hasJobNotes(job) && (
          <div className="follow-col">
            <FollowUpPanel
              key={`fu-${jobId}`}
              job={job}
              onSubmit={submit}
              busy={!!busy}
              onSelectFact={setSelectedFactId}
              onDraftChange={(dirty) => setDraftDirty("follow", dirty)}
            />
          </div>
        )}
        <FactsPanel
          key={`facts-${jobId}`}
          job={job}
          selectedFactId={selectedFactId}
          flashIds={flashIds}
          onSelectFact={setSelectedFactId}
          onConfirm={(factId) => run(UPDATING, () => api.confirmFact(jobId, factId))}
          onReview={(factId, value, state: FactState) =>
            run(UPDATING, () => api.reviewFact(jobId, factId, value, state))
          }
          busy={!!busy}
        />
        <aside className="col review-col">
          <ReportPanel job={job} health={health} onReview={() => setCloseoutOpen(true)} />
        </aside>
        <SourcePanel
          key={`notes-${jobId}`}
          variant="timeline"
          job={job}
          selectedFactId={selectedFactId}
          onSelectFact={setSelectedFactId}
          onSubmit={submit}
          onAddPhoto={(file, caption) => run(UPDATING, () => api.addPhoto(jobId, file, caption))}
          onEdit={(sourceId, text) => run(UPDATING, () => api.editSource(sourceId, text))}
          onRetry={(sourceId) => run(UPDATING, () => api.retrySource(sourceId))}
          busy={!!busy}
          voiceAvailable={voiceAvailable}
          voiceUnavailableReason={voiceUnavailableReason}
        />
      </main>
      {askOpen && (
        <AskPanel
          jobId={jobId}
          facts={job.facts}
          checklist={job.checklist}
          onClose={() => setAskOpen(false)}
          onCite={(item: AskItem) => {
            const factId = item.fact_ids[0];
            const sourceId = item.source_ids[0];
            const reqId = item.requirement_ids[0];
            if (factId) setSelectedFactId(factId);
            else if (sourceId) {
              const fromSource = job.facts.find((f) => f.source_id === sourceId);
              if (fromSource) setSelectedFactId(fromSource.id);
            } else if (reqId) {
              const req = job.checklist.find((r) => r.id === reqId);
              if (req?.fact_ids[0]) setSelectedFactId(req.fact_ids[0]);
            }
            const target = factId
              ? `fact-${factId}`
              : sourceId
                ? `source-${sourceId}`
                : reqId
                  ? `req-${reqId}`
                  : null;
            if (target) {
              window.setTimeout(() => document.getElementById(target)?.scrollIntoView({ block: "nearest" }), 0);
            }
          }}
        />
      )}
      {closeoutOpen && (
        <CloseoutPanel
          job={job}
          selectedFactId={selectedFactId}
          flashIds={flashIds}
          onSelectFact={setSelectedFactId}
          onConfirm={(factId) => run(UPDATING, () => api.confirmFact(jobId, factId))}
          onReview={(factId, value, state: FactState) =>
            run(UPDATING, () => api.reviewFact(jobId, factId, value, state))
          }
          onSubmit={submit}
          onClose={closeReview}
          onNewJob={props.onAllJobs}
          onNoteSaved={(next) => applyState(next)}
          onDraftChange={(dirty) => setDraftDirty("closeout", dirty)}
          busy={!!busy}
          voiceAvailable={voiceAvailable}
          voiceUnavailableReason={voiceUnavailableReason}
        />
      )}
    </div>
  );
}
