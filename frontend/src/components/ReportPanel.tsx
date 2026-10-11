import { closeoutHeadline, workRemains } from "../closeout";
import type { Health, JobState } from "../types";

interface Props {
  job: JobState;
  health: Health | null;
  onReview: () => void;
}

export default function ReportPanel({ job, health, onReview }: Props) {
  const run = job.last_run;
  const tokPerSec = run?.eval_tokens && run.eval_ms ? (run.eval_tokens / (run.eval_ms / 1000)).toFixed(1) : null;

  return (
    <>
      <div className="card review-card">
        <h2>Review before leaving</h2>
        <p className="review-summary">{closeoutHeadline(job)}</p>
        <p className="muted small">
          {workRemains(job)
            ? "Preview a report with unfinished work, or keep adding notes."
            : "Preview the completed-work report when you are ready."}{" "}
          Export does not change recorded facts. Reports stay on this device.
        </p>
        <button className="primary large" type="button" onClick={onReview}>
          Review before leaving
        </button>
      </div>

      <details className="card disclosure">
        <summary>Technical details</summary>
        <dl>
          <dt>Model</dt>
          <dd>
            {health?.model ?? "?"} {health?.parameter_size ?? ""} {health?.quantization ?? ""}
          </dd>
          <dt>Runtime</dt>
          <dd>{health ? (health.ollama_reachable ? "Ollama (local)" : "Ollama not reachable") : "?"}</dd>
          <dt>Device</dt>
          <dd>{health?.device ?? "?"}</dd>
          <dt>Speech</dt>
          <dd>{health?.whisper_available ? `whisper.cpp ${health.whisper_model}` : "not installed"}</dd>
          {run && (
            <>
              <dt>Last extraction</dt>
              <dd>
                {run.ok
                  ? `${Math.round(run.wall_ms ?? 0)} ms wall, ${run.prompt_tokens ?? "?"} prompt / ${run.eval_tokens ?? "?"} output tokens${tokPerSec ? `, ${tokPerSec} tok/s` : ""}`
                  : `failed: ${run.error}`}
              </dd>
            </>
          )}
        </dl>
        {health?.error && <p className="error small">{health.error}</p>}
        {job.rejected.length > 0 && (
          <>
            <h3>Proposals not applied (last run)</h3>
            <ul className="small">
              {job.rejected.map((rej, i) => (
                <li key={i}>
                  {rej.reason}: <code>{JSON.stringify(rej.proposal)}</code>
                </li>
              ))}
            </ul>
          </>
        )}
      </details>
    </>
  );
}
