import { useCallback, useEffect, useRef, useState, type FormEvent, type MouseEvent, type RefObject } from "react";
import { api } from "../api";
import { countedAsset, openChecks, pendingFacts, pinStatus, unresolvedIssues } from "../closeout";
import { describe, jobTitle } from "../format";
import type { MapJobItem, PinStatus, SiteMapState } from "../types";
import AppNav from "./AppNav";
import BrandLogo from "./BrandLogo";

interface Props {
  onOpenJob: (id: number) => void;
  onJobs: () => void;
  onHome: () => void;
}

type Mode = "idle" | "placing" | "moving";

const STATUS_LABEL: Record<PinStatus, string> = {
  open_problem: "Open problem",
  needs_attention: "Needs attention",
  no_open_items: "No open items recorded",
};

function imageBox(img: HTMLImageElement) {
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  const cw = img.clientWidth;
  const ch = img.clientHeight;
  if (!nw || !nh || !cw || !ch) return null;
  const scale = Math.min(cw / nw, ch / nh);
  const width = nw * scale;
  const height = nh * scale;
  return { left: (cw - width) / 2, top: (ch - height) / 2, width, height };
}

function clickToNorm(e: MouseEvent<HTMLImageElement>, img: HTMLImageElement) {
  const box = imageBox(img);
  if (!box) return null;
  const rect = img.getBoundingClientRect();
  const scaleX = rect.width / img.clientWidth;
  const scaleY = rect.height / img.clientHeight;
  if (!scaleX || !scaleY) return null;
  const x = (e.clientX - rect.left) / scaleX - box.left;
  const y = (e.clientY - rect.top) / scaleY - box.top;
  return { x: x / box.width, y: y / box.height };
}

function displayStatus(item: MapJobItem): { key: PinStatus | "unavailable"; label: string } {
  if (item.status_error || item.checklist == null || item.status == null) {
    return { key: "unavailable", label: "Status unavailable." };
  }
  const key = pinStatus({ facts: item.facts, checklist: item.checklist });
  return { key, label: STATUS_LABEL[key] };
}

function openItems(item: MapJobItem): string[] {
  if (!item.checklist) return [];
  const issues = unresolvedIssues(item).map((f) => describe(f));
  const pending = pendingFacts(item)
    .filter((f) => !(f.field === "issue" && f.state === "unresolved"))
    .map((f) => `${describe(f)} — please review`);
  const checks = openChecks({ checklist: item.checklist }).map((r) => r.label.replace(/^§?\d+\s*/, "") || r.label);
  return [...issues, ...pending, ...checks].slice(0, 6);
}

export default function SiteMap(props: Props) {
  const [data, setData] = useState<SiteMapState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [siteName, setSiteName] = useState("");
  const [uploading, setUploading] = useState(false);
  const [imageTick, setImageTick] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [layoutTick, setLayoutTick] = useState(0);
  const [percentX, setPercentX] = useState("50");
  const [percentY, setPercentY] = useState("50");
  const wanted = useRef(0);
  const imgRef = useRef<HTMLImageElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const gen = ++wanted.current;
    setError(null);
    try {
      const next = await api.getSiteMap();
      if (wanted.current !== gen) return;
      setData(next);
    } catch (e) {
      if (wanted.current !== gen) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState && document.visibilityState !== "visible") return;
      void load();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [load]);

  useEffect(() => {
    const onResize = () => setLayoutTick((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const selected = data?.jobs.find((j) => j.job.id === selectedId) ?? null;
  const q = query.trim().toLowerCase();
  const matches = (item: MapJobItem) => {
    if (!q) return true;
    return [jobTitle(item.job.title), item.job.location ?? "", countedAsset(item)?.value ?? ""].some((v) =>
      v.toLowerCase().includes(q),
    );
  };
  const unplaced = (data?.jobs ?? []).filter((j) => !j.pin && matches(j));
  const placed = (data?.jobs ?? []).filter((j) => j.pin && matches(j));

  const upload = async (file: File, confirmReplace = false) => {
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api.uploadSiteMap(file, siteName, confirmReplace);
      setData(next);
      setImageTick((n) => n + 1);
      setMode("idle");
      setNotice("Floor plan saved. It is a visual reference and is not analyzed by AI.");
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (message.startsWith("409:") && !confirmReplace) {
        if (window.confirm(`${message.replace(/^409:\s*/, "")}\n\nReplace the floor plan and clear pins?`)) {
          await upload(file, true);
        }
      } else {
        setError(message);
      }
    } finally {
      setUploading(false);
    }
  };

  const savePin = async (x: number, y: number) => {
    if (!selected) return;
    if (x < 0 || x > 1 || y < 0 || y > 1) {
      setError("Place the pin on the floor plan image, not the empty margin.");
      return;
    }
    setError(null);
    try {
      const pin = mode === "moving" ? await api.movePin(selected.job.id, x, y) : await api.placePin(selected.job.id, x, y);
      setData((cur) =>
        cur
          ? { ...cur, jobs: cur.jobs.map((j) => (j.job.id === pin.job_id ? { ...j, pin } : j)) }
          : cur,
      );
      setMode("idle");
      setNotice(mode === "moving" ? "Pin moved." : "Job placed on the floor plan.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const clickPlan = async (e: MouseEvent<HTMLImageElement>) => {
    if ((mode !== "placing" && mode !== "moving") || !imgRef.current) return;
    const point = clickToNorm(e, imgRef.current);
    if (!point) return;
    await savePin(point.x, point.y);
  };

  const savePercent = async (e: FormEvent) => {
    e.preventDefault();
    const x = Number(percentX) / 100;
    const y = Number(percentY) / 100;
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      setError("Enter horizontal and vertical positions between 0 and 100.");
      return;
    }
    await savePin(x, y);
  };

  const removeSelected = async () => {
    if (!selected?.pin) return;
    setError(null);
    try {
      await api.removePin(selected.job.id);
      setData((cur) =>
        cur
          ? { ...cur, jobs: cur.jobs.map((j) => (j.job.id === selected.job.id ? { ...j, pin: null } : j)) }
          : cur,
      );
      setMode("idle");
      setNotice("Pin removed. The job is still saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const pinStyle = (item: MapJobItem) => {
    void layoutTick;
    const img = imgRef.current;
    if (!item.pin || !img) return { display: "none" } as const;
    const box = imageBox(img);
    if (!box) return { display: "none" } as const;
    return {
      left: box.left + item.pin.x * box.width,
      top: box.top + item.pin.y * box.height,
    };
  };

  return (
    <div className="dashboard sitemap">
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
            <AppNav current="map" onHome={props.onHome} onJobs={props.onJobs} />
            <div className="topbar-actions">
              <button className="btn btn-secondary" type="button" onClick={() => void load()}>
                Refresh
              </button>
            </div>
          </div>
        </div>
        <div className="page-identity">
          <h1>Site map</h1>
        </div>
      </header>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <p className="muted small map-notice" role="status">
          {notice}
        </p>
      )}
      <main className="map-page">
        {!data ? (
          <p className="loading">{error ?? "Loading…"}</p>
        ) : !data.plan ? (
          <section className="map-empty">
            <h2>See where work needs attention.</h2>
            <p>Upload a floor plan, then place your jobs on it.</p>
            <UploadForm
              siteName={siteName}
              setSiteName={setSiteName}
              uploading={uploading}
              fileRef={fileRef}
              onFile={(file) => void upload(file)}
            />
          </section>
        ) : (
          <>
            <section className="map-stage">
              <div className="map-toolbar">
                <p className="muted small">{data.plan.name || "Floor plan"}</p>
                <div className="row" style={{ marginTop: 0 }}>
                  <button type="button" onClick={() => setZoom(1)}>
                    Fit to view
                  </button>
                  <button type="button" onClick={() => setZoom((z) => Math.min(3, z + 0.25))} aria-label="Zoom in">
                    Zoom in
                  </button>
                  <button type="button" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} aria-label="Zoom out">
                    Zoom out
                  </button>
                </div>
              </div>
              <div className="map-viewport">
                <div className="map-zoom" style={{ transform: `scale(${zoom})` }}>
                  <div className="map-frame">
                    <img
                      ref={imgRef}
                      src={`/api/site-map/image?t=${imageTick}`}
                      alt={data.plan.name ? `Floor plan for ${data.plan.name}` : "Site floor plan"}
                      className={mode === "idle" ? "floor-plan" : "floor-plan placing"}
                      onClick={(e) => void clickPlan(e)}
                      onLoad={() => setLayoutTick((n) => n + 1)}
                    />
                    {placed.map((item) => {
                      const st = displayStatus(item);
                      return (
                        <button
                          key={item.job.id}
                          type="button"
                          className={`map-pin ${st.key}${selectedId === item.job.id ? " selected" : ""}`}
                          style={pinStyle(item)}
                          aria-label={`${jobTitle(item.job.title)}. ${st.label}`}
                          onClick={() => {
                            setSelectedId(item.job.id);
                            setMode("idle");
                          }}
                        />
                      );
                    })}
                  </div>
                </div>
              </div>
              <p className="muted small map-hint">
                {mode === "placing"
                  ? "Click the floor plan to place the selected job."
                  : mode === "moving"
                    ? "Click the floor plan to move this pin."
                    : "Pins stay aligned to the image, including when the window is resized."}
              </p>
              <ul className="map-legend">
                <li><span className="map-pin open_problem" /> Open problem</li>
                <li><span className="map-pin needs_attention" /> Needs attention</li>
                <li><span className="map-pin no_open_items" /> No open items recorded</li>
              </ul>
              <UploadForm
                siteName={siteName}
                setSiteName={setSiteName}
                uploading={uploading}
                fileRef={fileRef}
                onFile={(file) => void upload(file)}
                compact
              />
            </section>
            <aside className="map-lists">
              <label className="search-field">
                <span className="muted small">Search jobs</span>
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Title, equipment, or location" />
              </label>
              <h2>Unplaced jobs</h2>
              {unplaced.length === 0 ? (
                <p className="muted small">No unplaced jobs match.</p>
              ) : (
                <ul className="map-job-list">
                  {unplaced.map((item) => (
                    <JobRow
                      key={item.job.id}
                      item={item}
                      selected={selectedId === item.job.id}
                      onSelect={() => setSelectedId(item.job.id)}
                    />
                  ))}
                </ul>
              )}
              {selected && !selected.pin && (
                <button
                  className="primary"
                  type="button"
                  disabled={!data.plan}
                  onClick={() => {
                    setMode("placing");
                    setNotice(null);
                  }}
                >
                  Place on map
                </button>
              )}
              {(mode === "placing" || mode === "moving") && selected && (
                <form className="pin-percent" onSubmit={(e) => void savePercent(e)}>
                  <p className="muted small">Or enter a position as a percent of the image.</p>
                  <div className="row">
                    <label>
                      <span className="muted small">Horizontal %</span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={0.1}
                        value={percentX}
                        onChange={(e) => setPercentX(e.target.value)}
                      />
                    </label>
                    <label>
                      <span className="muted small">Vertical %</span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={0.1}
                        value={percentY}
                        onChange={(e) => setPercentY(e.target.value)}
                      />
                    </label>
                    <button className="primary" type="submit">
                      Save pin
                    </button>
                  </div>
                </form>
              )}
              <h2>Placed jobs</h2>
              {placed.length === 0 ? (
                <p className="muted small">No jobs are on this floor plan yet.</p>
              ) : (
                <ul className="map-job-list">
                  {placed.map((item) => (
                    <JobRow
                      key={item.job.id}
                      item={item}
                      selected={selectedId === item.job.id}
                      onSelect={() => {
                        setSelectedId(item.job.id);
                        setMode("idle");
                      }}
                    />
                  ))}
                </ul>
              )}
              {selected?.pin && (
                <PinPanel
                  item={selected}
                  onOpen={() => props.onOpenJob(selected.job.id)}
                  onMove={() => setMode("moving")}
                  onRemove={() => void removeSelected()}
                />
              )}
            </aside>
          </>
        )}
      </main>
    </div>
  );
}

function UploadForm(props: {
  siteName: string;
  setSiteName: (v: string) => void;
  uploading: boolean;
  fileRef: RefObject<HTMLInputElement | null>;
  onFile: (file: File) => void;
  compact?: boolean;
}) {
  return (
    <form
      className={props.compact ? "map-replace" : "map-upload"}
      onSubmit={(e) => e.preventDefault()}
    >
      <label>
        <span className="muted small">Site name</span>
        <input
          value={props.siteName}
          onChange={(e) => props.setSiteName(e.target.value)}
          placeholder="Optional"
          maxLength={200}
        />
      </label>
      <label className="file-label">
        <span className="muted small">Floor plan (PNG or JPEG, 8 MB max)</span>
        <input
          ref={props.fileRef}
          type="file"
          accept="image/png,image/jpeg"
          aria-label="Upload floor plan"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) props.onFile(file);
          }}
        />
      </label>
      <p className="muted small">
        The image is a visual reference. It is stored on this computer and is not analyzed by AI.
      </p>
      {props.uploading && <p className="busy">Saving floor plan…</p>}
    </form>
  );
}

function JobRow(props: { item: MapJobItem; selected: boolean; onSelect: () => void }) {
  const st = displayStatus(props.item);
  return (
    <li>
      <button type="button" className={props.selected ? "map-job selected" : "map-job"} onClick={props.onSelect}>
        <strong>{jobTitle(props.item.job.title)}</strong>
        <span className={`status-dot ${st.key}`} aria-hidden="true" />
        <span className="muted small">{st.label}</span>
      </button>
    </li>
  );
}

function PinPanel(props: { item: MapJobItem; onOpen: () => void; onMove: () => void; onRemove: () => void }) {
  const { item } = props;
  const st = displayStatus(item);
  const issues = unresolvedIssues(item).length;
  const review = pendingFacts(item).length;
  const checks = item.checklist ? openChecks({ checklist: item.checklist }).length : null;
  const items = openItems(item);
  return (
    <section className="pin-panel" aria-label="Selected job">
      <h3>{jobTitle(item.job.title)}</h3>
      {countedAsset(item)?.value?.trim() && <p>{countedAsset(item)?.value}</p>}
      {item.job.location?.trim() && <p>{item.job.location}</p>}
      <p className={st.key === "unavailable" ? "muted" : undefined}>{st.label}</p>
      <ul className="count-row">
        <li>
          <strong>{issues}</strong> open issues
        </li>
        <li>
          <strong>{review}</strong> needs review
        </li>
        <li>
          <strong>{checks ?? "—"}</strong> incomplete checks
        </li>
      </ul>
      {items.length > 0 && (
        <ul className="open-items">
          {items.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
      <div className="row">
        <a className="button primary" href={`/jobs/${item.job.id}`} onClick={(e) => { e.preventDefault(); props.onOpen(); }}>
          Open job
        </a>
        <button type="button" onClick={props.onMove}>
          Reposition
        </button>
        <button type="button" onClick={props.onRemove}>
          Remove pin
        </button>
      </div>
    </section>
  );
}
