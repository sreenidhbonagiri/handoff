import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "../api";
import { factCiteLabel, isStaleAsk, missingInformationText, relatedOpenIssueCaption } from "../askGuard";
import { IconBot } from "../icons";
import type { AskAnswer, AskHistoryMessage, AskItem, Fact, RequirementStatus } from "../types";

const STARTERS = [
  "What’s still unfinished?",
  "What have we already tried?",
  "What should the next technician know?",
];

interface Props {
  jobId: number;
  facts: Fact[];
  checklist: RequirementStatus[];
  onClose: () => void;
  onCite: (item: AskItem) => void;
}

interface Turn {
  question: string;
  answer?: AskAnswer;
  error?: string;
}

export default function AskPanel(props: Props) {
  const { jobId } = props;
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const gen = useRef(0);
  const wanted = useRef(jobId);
  const abort = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  wanted.current = jobId;

  useEffect(() => {
    abort.current?.abort();
    abort.current = null;
    gen.current += 1;
    setTurns([]);
    setQuestion("");
    setBusy(false);
    stick.current = true;
    input.current?.focus();
  }, [jobId]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !busy) props.onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, props]);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    const el = thread.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [turns, busy]);

  const cancel = () => {
    abort.current?.abort();
    abort.current = null;
    gen.current += 1;
    setBusy(false);
  };

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const nextGen = ++gen.current;
    const forJob = jobId;
    const history = historyPayload(turns);
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    setBusy(true);
    setQuestion("");
    stick.current = true;
    setTurns((cur) => [...cur, { question: q }]);
    try {
      const answer = await api.askJob(forJob, q, history, ac.signal);
      if (isStaleAsk(wanted.current, answer.job_id, nextGen, gen.current)) return;
      setTurns((cur) => {
        const copy = [...cur];
        const last = copy[copy.length - 1];
        if (last && last.question === q && !last.answer) copy[copy.length - 1] = { question: q, answer };
        return copy;
      });
    } catch (e) {
      if (ac.signal.aborted) {
        if (wanted.current === forJob && gen.current === nextGen) {
          setTurns((cur) => cur.filter((t, i) => i !== cur.length - 1 || t.answer || t.error));
        }
        return;
      }
      if (isStaleAsk(wanted.current, forJob, nextGen, gen.current)) return;
      setTurns((cur) => {
        const copy = [...cur];
        const last = copy[copy.length - 1];
        if (last && !last.answer) {
          copy[copy.length - 1] = { question: q, error: e instanceof Error ? e.message : String(e) };
        }
        return copy;
      });
    } finally {
      if (wanted.current === forJob && gen.current === nextGen) setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(question);
  };

  const onComposerKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(question);
    }
  };

  const pending = busy && turns.length > 0 && !turns[turns.length - 1]?.answer && !turns[turns.length - 1]?.error;

  return (
    <div className="ask-overlay" onClick={() => { cancel(); props.onClose(); }}>
      <aside
        className="ask-panel"
        role="dialog"
        aria-labelledby="ask-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="ask-head">
          <div>
            <div className="ask-title-row">
              <IconBot />
              <h2 id="ask-title">Handoff Assistant</h2>
            </div>
            <p className="muted small">Ask about this job’s notes and open work.</p>
            <p className="muted small">
              Answers use this job’s saved notes. Asking a question does not update the job.
            </p>
            <p className="muted small">Chat is not saved to the report. It clears when you leave this job.</p>
            <p className="muted small ask-disclaimer">AI responses can make mistakes.</p>
          </div>
          <button type="button" onClick={() => { cancel(); props.onClose(); }} aria-label="Close ask panel">
            Close
          </button>
        </header>
        <div className="ask-starters" role="group" aria-label="Starter questions">
          {STARTERS.map((q) => (
            <button key={q} type="button" disabled={busy} onClick={() => void ask(q)}>
              {q}
            </button>
          ))}
        </div>
        <div
          ref={thread}
          className="ask-thread"
          aria-live="polite"
          onScroll={() => {
            const el = thread.current;
            if (!el) return;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          {turns.length === 0 && !busy && (
            <p className="muted small ask-empty">Choose a starter question or type your own.</p>
          )}
          {turns.map((turn, i) => (
            <article key={`${turn.question}-${i}`} className="ask-turn">
              <div className="ask-msg ask-msg-user">
                <p className="ask-msg-label">You</p>
                <div className="ask-bubble ask-bubble-user">
                  <Prose text={turn.question} />
                </div>
              </div>
              {turn.answer && (
                <AssistantMessage
                  answer={turn.answer}
                  facts={props.facts}
                  checklist={props.checklist}
                  onCite={props.onCite}
                />
              )}
              {turn.error && (
                <div className="ask-msg ask-msg-assistant">
                  <p className="ask-msg-label">
                    <IconBot /> Handoff
                  </p>
                  <div className="ask-bubble ask-bubble-assistant">
                    <p className="ask-error" role="alert">
                      {turn.error} Try asking again, or open the job notes if the model is unavailable.
                    </p>
                  </div>
                </div>
              )}
              {!turn.answer && !turn.error && pending && i === turns.length - 1 && <TypingIndicator />}
            </article>
          ))}
        </div>
        <form className="ask-form" onSubmit={submit}>
          <label>
            <span className="muted small">Message</span>
            <textarea
              ref={input}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={onComposerKey}
              rows={3}
              maxLength={500}
              disabled={busy}
              placeholder="Ask about this job, or type a question"
            />
          </label>
          <div className="row">
            <button className="btn btn-primary" type="submit" disabled={busy || !question.trim()}>
              {busy ? "Sending…" : "Send"}
            </button>
            {busy && (
              <button type="button" onClick={cancel}>
                Cancel
              </button>
            )}
          </div>
        </form>
      </aside>
    </div>
  );
}

function historyPayload(turns: Turn[]): AskHistoryMessage[] {
  const out: AskHistoryMessage[] = [];
  for (const turn of turns) {
    if (!turn.answer) continue;
    out.push({ role: "user", text: turn.question });
    out.push({
      role: "assistant",
      text: turn.answer.items.map((item) => item.text).filter(Boolean).join("\n"),
    });
  }
  return out.slice(-8);
}

function TypingIndicator() {
  return (
    <div className="ask-msg ask-msg-assistant">
      <p className="ask-msg-label">
        <IconBot /> Handoff
      </p>
      <div className="ask-bubble ask-bubble-assistant ask-typing" aria-live="polite">
        <span className="ask-dot" />
        <span className="ask-dot" />
        <span className="ask-dot" />
        <span className="visually-hidden">Handoff is writing…</span>
      </div>
    </div>
  );
}

function AssistantMessage(props: {
  answer: AskAnswer;
  facts: Fact[];
  checklist: RequirementStatus[];
  onCite: (item: AskItem) => void;
}) {
  const { answer } = props;
  return (
    <div className="ask-msg ask-msg-assistant">
      <p className="ask-msg-label">
        <IconBot /> Handoff
      </p>
      <div className="ask-bubble ask-bubble-assistant">
        {answer.kind === "general" && <p className="ask-kind-label">General information</p>}
        {answer.kind === "job" && <p className="ask-kind-label">Check the linked notes</p>}
        {answer.truncated && (
          <p className="muted small">
            This job is too large to include every older note. The answer may be incomplete.
          </p>
        )}
        {answer.items.map((item, j) => {
          const text =
            item.kind === "missing_information"
              ? missingInformationText(item.requirement_ids, props.checklist) || item.text
              : item.text;
          const hasEvidence = item.fact_ids.length + item.source_ids.length + item.requirement_ids.length > 0;
          const hasRelated = (item.related_fact_ids || []).length > 0;
          return (
            <div key={j} className="ask-item">
              <Prose text={text} />
              {(hasEvidence || hasRelated) && (
                <div className="ask-evidence">
                  {hasEvidence && (
                    <p className="ask-evidence-row">
                      <span className="ask-evidence-label">Supporting evidence</span>
                      <CiteButtons item={item} facts={props.facts} onCite={props.onCite} />
                    </p>
                  )}
                  <RelatedCites item={item} facts={props.facts} onCite={props.onCite} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Prose({ text }: { text: string }) {
  const blocks = text.replace(/\r\n/g, "\n").split(/\n{2,}/);
  return (
    <div className="ask-prose">
      {blocks.map((block, i) => {
        const lines = block.split("\n").map((line) => line.trimEnd()).filter((line) => line.trim());
        if (!lines.length) return null;
        const listed = lines.every((line) => /^[-*•]\s+/.test(line.trim()) || /^\d+[.)]\s+/.test(line.trim()));
        if (listed) {
          return (
            <ul key={i}>
              {lines.map((line, j) => (
                <li key={j}>{line.trim().replace(/^[-*•]\s+/, "").replace(/^\d+[.)]\s+/, "")}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i}>
            {lines.map((line, j) => (
              <span key={j}>
                {j > 0 ? <br /> : null}
                {line}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function FactCite(props: { id: number; facts: Fact[]; onClick: () => void }) {
  const fact = props.facts.find((f) => f.id === props.id);
  const status = fact ? factCiteLabel(fact) : null;
  return (
    <button type="button" className="link" onClick={props.onClick}>
      F{props.id}
      {status ? <span className="ask-cite-status"> {status}</span> : null}
    </button>
  );
}

function CiteButtons(props: { item: AskItem; facts: Fact[]; onCite: (item: AskItem) => void }) {
  const { item } = props;
  const facts = item.fact_ids;
  const sources = item.source_ids;
  const reqs = item.requirement_ids;
  if (!facts.length && !sources.length && !reqs.length) return null;
  return (
    <span className="ask-cites">
      {facts.map((id) => (
        <FactCite
          key={`f${id}`}
          id={id}
          facts={props.facts}
          onClick={() => props.onCite({ ...item, fact_ids: [id], source_ids: [], requirement_ids: [], related_fact_ids: [] })}
        />
      ))}
      {sources.map((id) => (
        <button key={`s${id}`} type="button" className="link" onClick={() => props.onCite({ ...item, source_ids: [id], fact_ids: [], requirement_ids: [], related_fact_ids: [] })}>
          S{id}
        </button>
      ))}
      {reqs.map((id) => (
        <button key={id} type="button" className="link" onClick={() => props.onCite({ ...item, requirement_ids: [id], fact_ids: [], source_ids: [], related_fact_ids: [] })}>
          {id}
        </button>
      ))}
    </span>
  );
}

function RelatedCites(props: { item: AskItem; facts: Fact[]; onCite: (item: AskItem) => void }) {
  const ids = props.item.related_fact_ids || [];
  if (!ids.length) return null;
  return (
    <p className="muted small ask-related">
      Related job context.{" "}
      <span className="ask-cites">
        {ids.map((id) => {
          const fact = props.facts.find((f) => f.id === id);
          const current = fact ? relatedOpenIssueCaption(fact) : null;
          return (
            <span key={`rel${id}`} className="ask-related-fact">
              {current ? <span>{current} </span> : null}
              <FactCite
                id={id}
                facts={props.facts}
                onClick={() => props.onCite({ ...props.item, fact_ids: [id], source_ids: [], requirement_ids: [], related_fact_ids: [] })}
              />
            </span>
          );
        })}
      </span>
    </p>
  );
}
