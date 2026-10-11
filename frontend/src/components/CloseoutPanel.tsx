import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import {
  attachedPhotos,
  canPrepareCompleted,
  closeoutHeadline,
  completedWork,
  openChecks,
  pendingFacts,
  unresolvedIssues,
  workRemains,
} from "../closeout";
import {
  badgeClass,
  checklistDetail,
  checklistTitle,
  describe,
  displayState,
  equipmentLine,
  followUpCopy,
  hasJobNotes,
  requirementBadge,
} from "../format";
import type { Fact, FactState, JobState, ObservationIn } from "../types";
import { printReport } from "../printReport";
import { FactCard } from "./FactsPanel";
import Recorder from "./Recorder";

export type ReportKind = "completed" | "handoff";

interface Props {
  job: JobState;
  selectedFactId: number | null;
  flashIds: Set<number>;
  onSelectFact: (id: number | null) => void;
  onConfirm: (factId: number) => void;
  onReview: (factId: number, value: string | null, state: FactState) => void;
  onSubmit: (obs: ObservationIn) => Promise<boolean>;
  onClose: () => void;
  onNewJob: () => void;
  onNoteSaved: (next: JobState) => void;
  onDraftChange?: (dirty: boolean) => void;
  busy: boolean;
  voiceAvailable: boolean;
  voiceUnavailableReason: string | null;
}

export default function CloseoutPanel(props: Props) {
  const { job } = props;
  const pending = pendingFacts(job);
  const checks = openChecks(job);
  const issues = unresolvedIssues(job);
  const done = completedWork(job);
  const photos = attachedPhotos(job);
  const completeOk = canPrepareCompleted(job);
  const handoffOk = workRemains(job);
  const q = job.next_question;

  const [note, setNote] = useState(job.job.handoff_note ?? "");
  const [noteStatus, setNoteStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [noteError, setNoteError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [answer, setAnswer] = useState("");
  const [preview, setPreview] = useState<ReportKind | null>(null);
  const [printing, setPrinting] = useState(false);
  const [printError, setPrintError] = useState<string | null>(null);
  const [fullPhoto, setFullPhoto] = useState<string | null>(null);
  const savedNote = useRef(job.job.handoff_note ?? "");
  const saveTimer = useRef<number | null>(null);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const stored = job.job.handoff_note ?? "";
    setNote(stored);
    savedNote.current = stored;
    setNoteStatus("idle");
    setNoteError(null);
    setPreview(null);
  }, [job.job.id]);

  useEffect(() => {
    setPreview(null);
  }, [job.facts.length, job.sources.length, job.readiness.ready]);

  useEffect(
    () => () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    },
    [],
  );

  useEffect(() => {
    titleRef.current?.focus();
  }, []);

  const draftCb = useRef(props.onDraftChange);
  draftCb.current = props.onDraftChange;
  useEffect(() => {
    const dirty = note !== savedNote.current || Boolean(answer.trim()) || noteStatus === "saving";
    draftCb.current?.(dirty);
    return () => draftCb.current?.(false);
  }, [note, answer, noteStatus]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (fullPhoto) setFullPhoto(null);
      else props.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullPhoto, props.onClose]);

  const persistNote = (text: string): Promise<boolean> => {
    if (inFlight.current) {
      return inFlight.current.then((ok) => (ok && savedNote.current === text ? true : persistNote(text)));
    }
    if (text === savedNote.current && noteStatus !== "error") {
      setNoteStatus(text ? "saved" : "idle");
      return Promise.resolve(true);
    }
    setNoteStatus("saving");
    setNoteError(null);
    const run = api
      .saveHandoffNote(job.job.id, text)
      .then((next) => {
        savedNote.current = next.job.handoff_note ?? "";
        props.onNoteSaved(next);
        setNoteStatus("saved");
        return true;
      })
      .catch((e) => {
        setNoteStatus("error");
        setNoteError(e instanceof Error ? e.message : String(e));
        return false;
      })
      .finally(() => {
        inFlight.current = null;
      });
    inFlight.current = run;
    return run;
  };

  const scheduleSave = (text: string) => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      void persistNote(text);
    }, 400);
  };

  const flushNote = async (): Promise<boolean> => {
    if (saveTimer.current) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
    }
    return persistNote(note);
  };

  const prepare = async (mode: ReportKind) => {
    if (preparing) return;
    setPreparing(true);
    setPreview(null);
    setPrintError(null);
    const ok = await flushNote();
    setPreparing(false);
    if (ok) setPreview(mode);
  };

  const printPdf = async () => {
    if (!preview || printing) return;
    setPrinting(true);
    setPrintError(null);
    const ok = await flushNote();
    if (!ok) {
      setPrinting(false);
      setPrintError("Could not save the handoff note.");
      return;
    }
    try {
      await printReport(api.reportHtmlUrl(job.job.id, { mode: preview }));
    } catch (e) {
      setPrintError(e instanceof Error ? e.message : String(e));
    } finally {
      setPrinting(false);
    }
  };

  const reportOpts = preview ? { mode: preview } : undefined;
  const factCard = {
    job,
    selectedFactId: props.selectedFactId,
    flashIds: props.flashIds,
    onSelectFact: props.onSelectFact,
    onConfirm: props.onConfirm,
    onReview: props.onReview,
    busy: props.busy,
    collapseEvidence: true,
  };

  return (
    <div
      className="closeout-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="closeout-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) props.onClose();
      }}
    >
      <div className="closeout-panel">
        <div className="closeout-head">
          <div>
            <h2 id="closeout-title" ref={titleRef} tabIndex={-1}>
              Review before leaving
            </h2>
            <p className="muted small">
              Job {job.job.id} · {job.job.title} · {equipmentLine(job)}
            </p>
          </div>
          <div className="row">
            <button type="button" onClick={props.onNewJob} disabled={props.busy}>
              New job
            </button>
            <button type="button" onClick={props.onClose}>
              Close
            </button>
          </div>
        </div>

        <div className="closeout-body">
          <p className="review-summary">{closeoutHeadline(job)}</p>
          <ul className="count-row">
            <li>
              <strong>{issues.length}</strong> open {issues.length === 1 ? "issue" : "issues"}
            </li>
            <li>
              <strong>{checks.length}</strong> missing {checks.length === 1 ? "check" : "checks"}
            </li>
            <li>
              <strong>{pending.length}</strong> {pending.length === 1 ? "item" : "items"} needing review
            </li>
          </ul>

          {q && hasJobNotes(job) && (
            <FollowUpBlock
              job={job}
              answer={answer}
              setAnswer={setAnswer}
              onSelectFact={props.onSelectFact}
              onSubmit={props.onSubmit}
              busy={props.busy}
              voiceAvailable={props.voiceAvailable}
              voiceUnavailableReason={props.voiceUnavailableReason}
            />
          )}

          <Section title="Items needing review" empty="Nothing is waiting for confirmation.">
            {pending.map((f) => (
              <FactCard key={f.id} fact={f} {...factCard} />
            ))}
          </Section>

          <Section title="Problems still open" empty="No open problems recorded.">
            {issues.map((f) => (
              <FactLine key={f.id} fact={f} selected={props.selectedFactId === f.id} onSelect={props.onSelectFact} />
            ))}
          </Section>

          <Section title="Missing checks" empty="No required checks are missing, planned, or not done yet.">
            {checks.map((r) => {
              const badge = requirementBadge(r, job);
              return (
                <li
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
          </Section>

          {done.length > 0 && (
            <details className="closeout-block">
              <summary>Completed work ({done.length})</summary>
              <div className="closeout-list">
                {done.map((f) => (
                  <FactLine key={f.id} fact={f} selected={props.selectedFactId === f.id} onSelect={props.onSelectFact} />
                ))}
              </div>
            </details>
          )}

          {photos.length > 0 && (
            <details className="closeout-block">
              <summary>Supporting photos ({photos.length})</summary>
              <div className="photo-strip">
                {photos.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className="thumb-wrap"
                    onClick={() => setFullPhoto(api.photoUrl(s.job_id, s.photo_path as string))}
                  >
                    <img className="thumb" src={api.photoUrl(s.job_id, s.photo_path as string)} alt={`Photo S${s.id}`} />
                    <span className="muted small">{s.text ? s.text : "No caption"}</span>
                  </button>
                ))}
              </div>
            </details>
          )}

          <div className="closeout-block">
            <label className="handoff-label" htmlFor="handoff-note">
              What should the next technician know?
            </label>
            <p className="muted small">Saved with this report. To update job progress, add this as a job note.</p>
            <textarea
              id="handoff-note"
              className="handoff-note"
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setPreview(null);
                setNoteStatus("idle");
                scheduleSave(e.target.value);
              }}
              onBlur={() => void flushNote()}
              rows={3}
              placeholder="Optional note for the next technician"
            />
            <p className={`small ${noteStatus === "error" ? "handoff-status-error" : "muted"}`} aria-live="polite">
              {noteStatus === "saving" && "Saving…"}
              {noteStatus === "saved" && "Saved with this job."}
              {noteStatus === "error" && (noteError ?? "Could not save the note.")}
            </p>
          </div>

          {preview && (
            <div className="closeout-block">
              <h3>{preview === "handoff" ? "Report with unfinished work" : "Completed-work preview"}</h3>
              <p className="muted small">This report is saved locally on this device. It is not uploaded.</p>
              <iframe
                className="report-frame"
                title="Prepared report preview"
                src={api.reportHtmlUrl(job.job.id, reportOpts)}
              />
              <div className="row print-actions">
                <button type="button" className="primary" disabled={printing} onClick={() => void printPdf()}>
                  {printing ? "Preparing PDF\u2026" : "Print / Save as PDF"}
                </button>
                <p className="muted small print-hint">Choose ‘Save as PDF’ in the print window.</p>
              </div>
              {printError && <p className="handoff-status-error small">{printError}</p>}
              <div className="row">
                <a className="button" href={api.reportHtmlUrl(job.job.id, reportOpts)} download={`handoff-job-${job.job.id}.html`}>
                  Export HTML
                </a>
                <a className="button" href={api.reportJsonUrl(job.job.id, reportOpts)} download={`handoff-job-${job.job.id}.json`}>
                  Export JSON
                </a>
              </div>
            </div>
          )}
        </div>

        <div className="closeout-footer">
          <div className="row">
            {handoffOk && (
              <button className="primary" type="button" disabled={preparing} onClick={() => void prepare("handoff")}>
                {preparing ? "Saving note…" : "Preview report with unfinished work"}
              </button>
            )}
            <button
              className={handoffOk ? undefined : "primary"}
              type="button"
              disabled={!completeOk || preparing}
              onClick={() => void prepare("completed")}
            >
              Preview completed-work report
            </button>
          </div>
          {!completeOk && (
            <p className="muted small">
              Completed-work preview is available when every required check is recorded and nothing is waiting for
              confirmation.
            </p>
          )}
        </div>
      </div>
      {fullPhoto && (
        <button type="button" className="lightbox" onClick={() => setFullPhoto(null)} aria-label="Close photo">
          <img src={fullPhoto} alt="Full size job photo" />
        </button>
      )}
    </div>
  );
}

function Section(props: { title: string; empty: string; children: ReactNode }) {
  const items = Array.isArray(props.children) ? props.children.filter(Boolean) : props.children ? [props.children] : [];
  return (
    <div className="closeout-block">
      <h3>{props.title}</h3>
      {items.length === 0 ? <p className="muted small">{props.empty}</p> : <div className="closeout-list">{props.children}</div>}
    </div>
  );
}

function FactLine(props: { fact: Fact; selected: boolean; onSelect: (id: number | null) => void }) {
  const f = props.fact;
  return (
    <div className={`fact ${props.selected ? "selected" : ""}`} onClick={() => props.onSelect(f.id)}>
      <div className="fact-head">
        <strong>{describe(f)}</strong>
        <span className={`badge ${badgeClass(f)}`}>{displayState(f)}</span>
      </div>
      <details className="evidence">
        <summary>See original note</summary>
        <div className="quote small">
          S{f.source_id}: “{f.quote}”
        </div>
      </details>
    </div>
  );
}

function FollowUpBlock(props: {
  job: JobState;
  answer: string;
  setAnswer: (v: string | ((prev: string) => string)) => void;
  onSelectFact: (id: number | null) => void;
  onSubmit: (obs: ObservationIn) => Promise<boolean>;
  busy: boolean;
  voiceAvailable: boolean;
  voiceUnavailableReason: string | null;
}) {
  const q = props.job.next_question;
  const copy = followUpCopy(props.job);
  if (!q || !copy) return null;
  return (
    <div className="closeout-block">
      <h3>A quick question about this job</h3>
      <p className="follow-up-reason">{copy.reason}</p>
      <p className="question">{copy.question}</p>
      {q.fact_ids.length > 0 && (
        <div className="row small">
          {q.fact_ids.map((id) => (
            <button key={id} className="link" type="button" onClick={() => props.onSelectFact(id)}>
              See original note
            </button>
          ))}
        </div>
      )}
      <FollowUpInput
        job={props.job}
        answer={props.answer}
        setAnswer={props.setAnswer}
        onSubmit={props.onSubmit}
        busy={props.busy}
        voiceAvailable={props.voiceAvailable}
        voiceUnavailableReason={props.voiceUnavailableReason}
      />
    </div>
  );
}

function FollowUpInput(props: {
  job: JobState;
  answer: string;
  setAnswer: (v: string | ((prev: string) => string)) => void;
  onSubmit: (obs: ObservationIn) => Promise<boolean>;
  busy: boolean;
  voiceAvailable: boolean;
  voiceUnavailableReason: string | null;
}) {
  const q = props.job.next_question;
  const copy = followUpCopy(props.job);
  const [submitting, setSubmitting] = useState(false);
  const [voice, setVoice] = useState<{
    audio_path: string;
    segments: ObservationIn["segments"];
    original: string;
    convert_ms: number;
    whisper_ms: number;
  } | null>(null);

  const send = async (obs: ObservationIn) => {
    if (submitting || props.busy) return;
    setSubmitting(true);
    const ok = await props.onSubmit(obs);
    setSubmitting(false);
    if (ok) {
      props.setAnswer("");
      setVoice(null);
    }
  };

  return (
    <div className="composer">
      <textarea
        value={props.answer}
        onChange={(e) => props.setAnswer(e.target.value)}
        rows={2}
        placeholder={copy?.placeholder ?? "For example: ‘It passed’ or ‘I haven’t tested it yet.’"}
        readOnly={submitting}
      />
      <p className="muted small">{copy?.helper ?? "Your answer will be added to the job notes."}</p>
      {voice && (
        <div className="voice-review small">
          <strong>Review the transcript before saving.</strong>
          {props.answer.trim() !== voice.original && (
            <div className="muted">Edited. Original transcript is kept: “{voice.original}”</div>
          )}
        </div>
      )}
      <div className="row">
        <Recorder
          disabled={props.busy || submitting || !props.voiceAvailable || voice !== null}
          unavailableReason={props.voiceAvailable ? null : props.voiceUnavailableReason}
          onTranscript={(out) => {
            props.setAnswer((prev) => (prev.trim() ? `${prev.trim()} ${out.text}` : out.text));
            setVoice({
              audio_path: out.audio_path,
              segments: out.segments,
              original: out.text,
              convert_ms: out.convert_ms,
              whisper_ms: out.whisper_ms,
            });
          }}
        />
        <button
          className="primary"
          type="button"
          disabled={props.busy || submitting || !props.answer.trim()}
          onClick={() =>
            void send(
              voice
                ? {
                    text: props.answer.trim(),
                    kind: "voice",
                    audio_path: voice.audio_path,
                    segments: voice.segments ?? null,
                    original_transcript: voice.original,
                    transcription_ms: voice.convert_ms + voice.whisper_ms,
                    answers_requirement: q?.requirement_id ?? null,
                  }
                : {
                    text: props.answer.trim(),
                    kind: q ? "answer" : "typed",
                    answers_requirement: q?.requirement_id ?? null,
                  },
            )
          }
        >
          {submitting ? "Updating your job…" : "Save answer"}
        </button>
      </div>
    </div>
  );
}
