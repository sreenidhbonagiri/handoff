import { useState } from "react";
import type { Fact, FactState, JobState } from "../types";
import { ALLOWED_STATES } from "../types";
import {
  REVIEW_LABEL,
  STATE_LABEL,
  ambiguousIssueResolution,
  badgeClass,
  checklistDetail,
  checklistTitle,
  describe,
  displayState,
  friendlyDiagnostics,
  groupActiveFacts,
  isPending,
  proposedChange,
  requirementBadge,
} from "../format";

interface Props {
  job: JobState;
  selectedFactId: number | null;
  flashIds: Set<number>;
  onSelectFact: (id: number | null) => void;
  onConfirm: (factId: number) => void;
  onReview: (factId: number, value: string | null, state: FactState) => void;
  busy: boolean;
  collapseEvidence?: boolean;
}

export default function FactsPanel(props: Props) {
  const { job } = props;
  const { review, attention, recorded } = groupActiveFacts(job.facts);
  const history = job.facts.filter((f) => f.superseded_by !== null && !f.invalidated);

  return (
    <section className="col facts-col">
      <div className="card">
        <h2>Job checklist</h2>
        <details className="procedure-note">
          <summary>About this sample procedure</summary>
          <p className="muted small">{job.procedure_title}</p>
        </details>
        <ul className="checklist">
          {job.checklist.map((r) => {
            const badge = requirementBadge(r, job);
            return (
              <li
                id={`req-${r.id}`}
                key={r.id}
                className={`req ${r.status}`}
                onClick={() => r.fact_ids[0] && props.onSelectFact(r.fact_ids[0])}
              >
                <span className={`pill ${badge.className}`}>{badge.text}</span>
                <div>
                  <div>{checklistTitle(r.id, r.label)}</div>
                  <div className="muted small">{checklistDetail(r, job)}</div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {review.length > 0 && (
        <FactGroup title="Please review" facts={review} {...props} />
      )}
      {attention.length > 0 && (
        <FactGroup title="Still needs attention" facts={attention} {...props} />
      )}
      {recorded.length > 0 && (
        <FactGroup title="Work recorded" facts={recorded} {...props} />
      )}
      {review.length + attention.length + recorded.length === 0 && (
        <p className="muted">Nothing recorded yet.</p>
      )}

      {history.length > 0 && (
        <details className="history">
          <summary>Earlier versions ({history.length})</summary>
          {history.map((f) => (
            <div
              id={`fact-${f.id}`}
              key={f.id}
              className={`fact superseded ${props.selectedFactId === f.id ? "selected" : ""}`}
              onClick={() => props.onSelectFact(f.id)}
            >
              <s>
                {describe(f)} — {STATE_LABEL[f.state]}
              </s>
              <details className="evidence">
                <summary>See original note</summary>
                <div className="quote small">
                  S{f.source_id}: “{f.quote}”
                </div>
                <div className="muted small">Replaced by a later note.</div>
              </details>
            </div>
          ))}
        </details>
      )}
    </section>
  );
}

function FactGroup(props: Props & { title: string; facts: Fact[] }) {
  return (
    <div className="fact-group">
      <h2>{props.title}</h2>
      {props.facts.map((f) => (
        <FactCard key={f.id} fact={f} {...props} />
      ))}
    </div>
  );
}

export function FactCard(props: Props & { fact: Fact }) {
  const { fact: f } = props;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(f.value ?? "");
  const [state, setState] = useState<FactState>(f.state);
  const conflicting = f.review_status === "conflicting";
  const held = f.review_status === "needs_review";
  const pending = isPending(f);
  const blocked = ambiguousIssueResolution(f, props.job);
  const diagnostics = friendlyDiagnostics(f.note);
  const source = props.job.sources.find((s) => s.id === f.source_id);
  const fromCaption = source?.kind === "photo";

  return (
    <div
      id={`fact-${f.id}`}
      className={[
        "fact",
        pending ? "conflicting" : "",
        props.selectedFactId === f.id ? "selected" : "",
        props.flashIds.has(f.id) ? "flash" : "",
      ].join(" ")}
      onClick={() => props.onSelectFact(f.id)}
    >
      <div className="fact-head">
        <strong>{describe(f)}</strong>
        <span className={`badge ${badgeClass(f)}`}>{displayState(f)}</span>
        {f.review_status === "confirmed" && <span className="badge confirmed">{REVIEW_LABEL.confirmed}</span>}
      </div>
      {pending && <p className="pending-note small">{proposedChange(f, props.job)}</p>}
      {blocked && (
        <p className="pending-note small">
          This statement does not say which issue it replaces. Edit it to name the issue before confirming.
        </p>
      )}
      {diagnostics.helpful
        .filter((msg) => pending || msg.startsWith("Taken from the photo"))
        .map((msg) => (
          <p key={msg} className="helpful-note small">
            {msg}
          </p>
        ))}
      <details className="evidence">
        <summary>See original note</summary>
        {f.corrected_from && <div className="corr small">Corrected from “{f.corrected_from}”</div>}
        <div className="quote small">
          {fromCaption ? `Caption on photo S${f.source_id} (not visual analysis)` : `S${f.source_id}`}: “{f.quote}”
        </div>
      </details>
      <details className="tech-details">
        <summary>Technical details</summary>
        <dl>
          <dt>Status stored</dt>
          <dd>
            {f.state} / {f.review_status}
          </dd>
          <dt>Note ID</dt>
          <dd>{f.id}</dd>
          <dt>Source</dt>
          <dd>S{f.source_id}</dd>
          {diagnostics.raw && (
            <>
              <dt>Internal note</dt>
              <dd>{diagnostics.raw}</dd>
            </>
          )}
        </dl>
      </details>
      {editing ? (
        <div className="row small" onClick={(e) => e.stopPropagation()}>
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" />
          <select value={state} onChange={(e) => setState(e.target.value as FactState)}>
            {ALLOWED_STATES[f.field].map((s) => (
              <option key={s} value={s}>
                {STATE_LABEL[s]}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            className="primary"
            type="button"
            disabled={props.busy}
            onClick={() => {
              setEditing(false);
              props.onReview(f.id, value.trim() || null, state);
            }}
          >
            Save
          </button>
        </div>
      ) : (
        <div className="row small" onClick={(e) => e.stopPropagation()}>
          {conflicting && (
            <button className="primary" type="button" disabled={props.busy} onClick={() => props.onConfirm(f.id)}>
              This one is correct
            </button>
          )}
          {held && !blocked && (
            <button className="primary" type="button" disabled={props.busy} onClick={() => props.onConfirm(f.id)}>
              Confirm as stated
            </button>
          )}
          <button className="link" type="button" disabled={props.busy} onClick={() => setEditing(true)}>
            Edit
          </button>
        </div>
      )}
    </div>
  );
}
