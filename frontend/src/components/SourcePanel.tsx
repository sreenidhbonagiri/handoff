import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { sourceKindLabel } from "../format";
import type { Fact, JobState, ObservationIn, Segment, Source } from "../types";
import { IconCamera, IconSave } from "../icons";
import Recorder from "./Recorder";

const MAX_PHOTO_BYTES = 8 * 1024 * 1024;

interface Props {
  job: JobState;
  selectedFactId: number | null;
  onSelectFact: (id: number | null) => void;
  onSubmit: (obs: ObservationIn) => Promise<boolean>;
  onAddPhoto: (file: File, caption: string) => Promise<boolean>;
  onEdit: (sourceId: number, text: string) => void;
  onRetry: (sourceId: number) => void;
  busy: boolean;
  voiceAvailable: boolean;
  voiceUnavailableReason: string | null;
  variant?: "full" | "composer" | "timeline";
  onDraftChange?: (dirty: boolean) => void;
}

interface VoiceMeta {
  audio_path: string;
  segments: Segment[];
  original: string;
  convert_ms: number;
  whisper_ms: number;
  duration_ms: number;
  model: string;
}

const ms = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

export default function SourcePanel(props: Props) {
  const { job, busy } = props;
  const variant = props.variant ?? "full";
  const showComposer = variant !== "timeline";
  const showTimeline = variant !== "composer";
  const [text, setText] = useState("");
  const [voice, setVoice] = useState<VoiceMeta | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [photoDraft, setPhotoDraft] = useState<{ file: File; url: string } | null>(null);
  const [caption, setCaption] = useState("");
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [fullPhoto, setFullPhoto] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const draftCb = useRef(props.onDraftChange);
  draftCb.current = props.onDraftChange;

  useEffect(() => {
    if (!showComposer) return;
    draftCb.current?.(Boolean(text.trim() || voice || photoDraft));
    return () => draftCb.current?.(false);
  }, [showComposer, text, voice, photoDraft]);

  const submit = async () => {
    const reviewed = text.trim();
    if (!reviewed || submitting || busy) return;
    setSubmitting(true);
    const ok = await props.onSubmit({
      text: reviewed,
      kind: voice ? "voice" : "typed",
      audio_path: voice?.audio_path ?? null,
      segments: voice?.segments ?? null,
      original_transcript: voice?.original ?? null,
      transcription_ms: voice ? voice.convert_ms + voice.whisper_ms : null,
    });
    setSubmitting(false);
    if (ok) {
      setText("");
      setVoice(null);
    }
  };

  const [discardError, setDiscardError] = useState<string | null>(null);

  const discardVoice = async () => {
    if (!voice) return;
    setDiscardError(null);
    try {
      await api.discardRecording(voice.audio_path);
      setText("");
      setVoice(null);
    } catch (e) {
      setDiscardError(e instanceof Error ? e.message : String(e));
    }
  };

  // A transcript still under review when the tab closes is discarded, so its audio is not left behind.
  useEffect(() => {
    if (!voice) return;
    const onHide = () => void api.discardRecording(voice.audio_path).catch(() => undefined);
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [voice]);

  // The same applies when the panel unmounts because another job was opened.
  const pendingPhoto = useRef<string | null>(null);
  pendingPhoto.current = photoDraft?.url ?? null;
  useEffect(
    () => () => {
      if (pendingPhoto.current) URL.revokeObjectURL(pendingPhoto.current);
    },
    [],
  );

  const pendingAudio = useRef<string | null>(null);
  pendingAudio.current = voice?.audio_path ?? null;
  useEffect(
    () => () => {
      if (pendingAudio.current) void api.discardRecording(pendingAudio.current).catch(() => undefined);
    },
    [],
  );

  const factsBySource = new Map<number, Fact[]>();
  for (const f of job.facts) {
    if (!f.active) continue;
    factsBySource.set(f.source_id, [...(factsBySource.get(f.source_id) ?? []), f]);
  }
  const selected = job.facts.find((f) => f.id === props.selectedFactId) ?? null;

  return (
    <section className={variant === "composer" ? "note-entry" : "col notes-col"}>
      {showComposer && (
      <div className={`card composer ${variant === "composer" ? "composer-wide" : ""}`}>
        <h2>Add a job note</h2>
        <p className="muted small">
          Tell us what you worked on, what you changed, and anything still wrong. You can type or record your voice.
        </p>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type or record a note"
          rows={4}
          readOnly={submitting}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
          }}
        />
        {voice && (
          <div className="voice-review small">
            <div>
              <strong>Review the transcript before saving.</strong>
            </div>
            {text.trim() !== voice.original && (
              <div className="muted">
                Edited. Original transcript is kept: “{voice.original}”
              </div>
            )}
            <details className="tech-details">
              <summary>Technical details</summary>
              Transcribed locally with whisper.cpp {voice.model} in {ms(voice.convert_ms + voice.whisper_ms)}{" "}
              (conversion {ms(voice.convert_ms)}, speech model {ms(voice.whisper_ms)}) from {ms(voice.duration_ms)} of
              audio.
            </details>
          </div>
        )}
        {photoDraft && (
          <div className="photo-draft">
            <img src={photoDraft.url} alt="Selected photo preview" className="photo-preview" />
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              placeholder="Optional caption. The photo is stored as evidence; only this caption is extracted."
              rows={2}
              readOnly={submitting}
            />
            <p className="muted small">The on-device model does not look at the photo. A photo alone does not mark work complete.</p>
          </div>
        )}
        <div className="row">
          <Recorder
            disabled={busy || submitting || !props.voiceAvailable || voice !== null || photoDraft !== null}
            unavailableReason={props.voiceAvailable ? null : props.voiceUnavailableReason}
            onTranscript={(out) => {
              setText((prev) => (prev.trim() ? `${prev.trim()} ${out.text}` : out.text));
              setVoice({
                audio_path: out.audio_path,
                segments: out.segments,
                original: out.text,
                convert_ms: out.convert_ms,
                whisper_ms: out.whisper_ms,
                duration_ms: out.duration_ms,
                model: out.model,
              });
            }}
          />
          <input
            ref={fileInput}
            type="file"
            accept="image/jpeg,image/png,.jpg,.jpeg,.png"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              setPhotoError(null);
              if (!file) return;
              if (file.size > MAX_PHOTO_BYTES) {
                setPhotoError("The photo is too large (limit 8 MB).");
                return;
              }
              if (photoDraft) URL.revokeObjectURL(photoDraft.url);
              setPhotoDraft({ file, url: URL.createObjectURL(file) });
              setCaption("");
            }}
          />
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy || submitting || voice !== null}
            onClick={() => fileInput.current?.click()}
          >
            <IconCamera />
            Add a photo
          </button>
          {photoDraft ? (
            <>
              <button
                className="btn btn-primary"
                type="button"
                disabled={busy || submitting}
                onClick={() => {
                  void (async () => {
                    setSubmitting(true);
                    setPhotoError(null);
                    const ok = await props.onAddPhoto(photoDraft.file, caption);
                    setSubmitting(false);
                    if (ok) {
                      URL.revokeObjectURL(photoDraft.url);
                      setPhotoDraft(null);
                      setCaption("");
                    }
                  })();
                }}
              >
                <IconSave />
                {submitting ? "Updating your job\u2026" : "Save photo"}
              </button>
              <button
                className="link"
                type="button"
                disabled={submitting}
                onClick={() => {
                  URL.revokeObjectURL(photoDraft.url);
                  setPhotoDraft(null);
                  setCaption("");
                  setPhotoError(null);
                }}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => void submit()}
              disabled={busy || submitting || !text.trim()}
            >
              <IconSave />
              {submitting ? "Updating your job\u2026" : "Save note"}
            </button>
          )}
          {voice && (
            <button className="link" type="button" onClick={() => void discardVoice()} disabled={submitting}>
              Discard
            </button>
          )}
          {discardError && <div className="voice-error small">{discardError}</div>}
          {photoError && <div className="voice-error small">{photoError}</div>}
        </div>
      </div>
      )}

      {showTimeline && (
      <>
      <h2>Notes and photos</h2>
      {job.sources.length === 0 && <p className="muted">No notes yet.</p>}
      <ol className="timeline">
        {job.sources.map((s) => (
          <SourceItem
            key={s.id}
            source={s}
            facts={factsBySource.get(s.id) ?? []}
            selected={selected?.source_id === s.id ? selected : null}
            onSelectFact={props.onSelectFact}
            onEdit={props.onEdit}
            onRetry={props.onRetry}
            onOpenPhoto={setFullPhoto}
            busy={busy}
          />
        ))}
      </ol>
      {fullPhoto && (
        <button type="button" className="lightbox" onClick={() => setFullPhoto(null)} aria-label="Close photo">
          <img src={fullPhoto} alt="Full size job photo" />
        </button>
      )}
      </>
      )}
    </section>
  );
}

function SourceItem(props: {
  source: Source;
  facts: Fact[];
  selected: Fact | null;
  onSelectFact: (id: number | null) => void;
  onEdit: (sourceId: number, text: string) => void;
  onRetry: (sourceId: number) => void;
  onOpenPhoto: (url: string) => void;
  busy: boolean;
}) {
  const { source: s, facts, selected } = props;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(s.text);
  const replaced = s.replaced_by !== null;

  return (
    <li id={`source-${s.id}`} className={`source ${replaced ? "replaced" : ""} ${selected ? "has-selection" : ""}`}>
      <div className="source-head">
        <strong>S{s.id}</strong>
        <span className="tag">{sourceKindLabel(s.kind)}</span>
        <span className="muted small">{new Date(s.created_at).toLocaleTimeString()}</span>
        {s.revises && <span className="muted small">edit of S{s.revises}</span>}
        {replaced && <span className="muted small">replaced by S{s.replaced_by}</span>}
      </div>
      {s.photo_path && (
        <button
          type="button"
          className="thumb-wrap"
          onClick={() => props.onOpenPhoto(api.photoUrl(s.job_id, s.photo_path as string))}
        >
          <img className="thumb" src={api.photoUrl(s.job_id, s.photo_path)} alt={`Photo S${s.id}`} />
        </button>
      )}
      {editing ? (
        <div className="composer">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} />
          <div className="row">
            <button onClick={() => setEditing(false)}>Cancel</button>
            <button
              className="primary"
              disabled={props.busy || draft === s.text}
              onClick={() => {
                setEditing(false);
                props.onEdit(s.id, draft.trim());
              }}
            >
              Save and re-interpret
            </button>
          </div>
        </div>
      ) : (
        <p className="source-text">
          {s.kind === "photo" && !s.text ? (
            <span className="muted">No caption. The photo was not analyzed.</span>
          ) : (
            <Highlighted text={s.text} facts={facts} selected={selected} onSelectFact={props.onSelectFact} />
          )}
        </p>
      )}
      {(s.transcription_ms !== null || s.extraction_ms !== null) && (
        <details className="tech-details">
          <summary>Technical details</summary>
          <div className="muted small">
            {s.transcription_ms !== null && `Transcription ${ms(s.transcription_ms)}`}
            {s.transcription_ms !== null && s.extraction_ms !== null && " · "}
            {s.extraction_ms !== null && `Extraction ${ms(s.extraction_ms)}`}
          </div>
        </details>
      )}
      {s.original_transcript && s.original_transcript !== s.text && (
        <details className="small">
          <summary className="muted">Original transcript (before review)</summary>
          <div className="muted">“{s.original_transcript}”</div>
        </details>
      )}
      {!replaced && !editing && s.kind !== "review" && (
        <div className="row small">
          <button className="link" onClick={() => setEditing(true)} disabled={props.busy}>
            {s.kind === "photo" ? (s.text ? "Edit caption" : "Add caption") : "Correct transcript"}
          </button>
          <button
            className="link"
            onClick={() => props.onRetry(s.id)}
            disabled={props.busy || (s.kind === "photo" && !s.text.trim())}
          >
            Re-run extraction
          </button>
        </div>
      )}
    </li>
  );
}

function Highlighted(props: {
  text: string;
  facts: Fact[];
  selected: Fact | null;
  onSelectFact: (id: number | null) => void;
}) {
  const { text, facts, selected } = props;
  const spans = [...facts].sort((a, b) => a.quote_start - b.quote_start);
  const pieces: ReactNode[] = [];
  let cursor = 0;
  for (const f of spans) {
    if (f.quote_start < cursor) continue;
    if (f.quote_start > cursor) pieces.push(text.slice(cursor, f.quote_start));
    pieces.push(
      <mark
        key={f.id}
        className={selected?.id === f.id ? "selected" : ""}
        onClick={() => props.onSelectFact(f.id)}
        title={`Fact ${f.id}`}
      >
        {text.slice(f.quote_start, f.quote_end)}
      </mark>,
    );
    cursor = f.quote_end;
  }
  if (selected && !spans.some((f) => f.id === selected.id)) {
    return (
      <>
        {text.slice(0, selected.quote_start)}
        <mark className="selected">{text.slice(selected.quote_start, selected.quote_end)}</mark>
        {text.slice(selected.quote_end)}
      </>
    );
  }
  pieces.push(text.slice(cursor));
  return <>{pieces}</>;
}
