import { useEffect, useRef, useState } from "react";
import { followUpCopy } from "../format";
import type { JobState, ObservationIn } from "../types";

interface Props {
  job: JobState;
  onSubmit: (obs: ObservationIn) => Promise<boolean>;
  onSelectFact: (id: number | null) => void;
  busy: boolean;
  onDraftChange?: (dirty: boolean) => void;
}

export default function FollowUpPanel({ job, onSubmit, onSelectFact, busy, onDraftChange }: Props) {
  const [answer, setAnswer] = useState("");
  const q = job.next_question;
  const copy = followUpCopy(job);
  const draftCb = useRef(onDraftChange);
  draftCb.current = onDraftChange;

  useEffect(() => {
    draftCb.current?.(Boolean(answer.trim()));
    return () => draftCb.current?.(false);
  }, [answer]);

  if (!q || !copy) return null;

  return (
    <div className="card follow-up-card compact">
      <h2>A quick question about this job</h2>
      <p className="follow-up-reason">{copy.reason}</p>
      <p className="question">{copy.question}</p>
      {q.fact_ids.length > 0 && (
        <div className="row small">
          {q.fact_ids.map((id) => (
            <button key={id} className="link" type="button" onClick={() => onSelectFact(id)}>
              See original note
            </button>
          ))}
        </div>
      )}
      <textarea
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        rows={2}
        placeholder={copy.placeholder}
        readOnly={busy}
        autoFocus={false}
      />
      <p className="muted small">{copy.helper}</p>
      <button
        className="primary"
        type="button"
        disabled={busy || !answer.trim()}
        onClick={async () => {
          if (await onSubmit({ text: answer.trim(), kind: "answer", answers_requirement: q.requirement_id })) {
            setAnswer("");
          }
        }}
      >
        Save answer
      </button>
    </div>
  );
}
