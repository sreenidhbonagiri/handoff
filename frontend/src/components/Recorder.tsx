import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { IconMic } from "../icons";
import type { TranscribeOut } from "../types";

interface Props {
  disabled: boolean;
  unavailableReason: string | null;
  onTranscript: (out: TranscribeOut) => void;
}

type Phase = "idle" | "requesting" | "recording" | "transcribing";

const MIN_RECORDING_MS = 500;

function micError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access was denied. Allow microphone access for this page in the browser (and for the browser in System Settings > Privacy & Security > Microphone), then try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found. Connect or enable a microphone and try again.";
  if (name === "NotReadableError") return "The microphone is in use by another app or could not be started.";
  return `Could not start recording: ${e instanceof Error ? e.message : String(e)}`;
}

// Click to start, click to stop. Audio goes to the local backend (ffmpeg + whisper.cpp);
// browser speech recognition is never used. The transcript is handed back for review, never submitted here.
export default function Recorder({ disabled, unavailableReason, onTranscript }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);

  useEffect(() => {
    if (phase !== "recording") return;
    const timer = window.setInterval(() => setElapsed(Date.now() - startedAt.current), 200);
    return () => window.clearInterval(timer);
  }, [phase]);

  useEffect(
    () => () => {
      if (recorder.current) recorder.current.onstop = null;
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const transcribe = async (blob: Blob, durationMs: number) => {
    if (durationMs < MIN_RECORDING_MS || blob.size === 0) {
      setError("The recording was too short. Click Record a note, speak, then click Stop.");
      setPhase("idle");
      return;
    }
    setPhase("transcribing");
    try {
      const out = await api.transcribe(blob);
      if (!out.text.trim()) {
        setError("No speech was recognized. Nothing was added.");
      } else {
        onTranscript(out);
      }
    } catch (e) {
      setError(`Transcription failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPhase("idle");
    }
  };

  const start = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser cannot record audio here. Open the app at http://127.0.0.1 in Chrome or Safari.");
      return;
    }
    setPhase("requesting");
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setError(micError(e));
      setPhase("idle");
      return;
    }
    stream.current = media;
    const rec = MediaRecorder.isTypeSupported("audio/webm") ? new MediaRecorder(media, { mimeType: "audio/webm" }) : new MediaRecorder(media);
    chunks.current = [];
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.current.push(e.data);
    };
    rec.onerror = () => setError("Recording failed in the browser.");
    rec.onstop = () => {
      media.getTracks().forEach((t) => t.stop());
      stream.current = null;
      const duration = Date.now() - startedAt.current;
      void transcribe(new Blob(chunks.current, { type: rec.mimeType || "audio/webm" }), duration);
    };
    startedAt.current = Date.now();
    setElapsed(0);
    rec.start();
    recorder.current = rec;
    setPhase("recording");
  };

  const stop = () => {
    if (recorder.current?.state === "recording") recorder.current.stop();
    recorder.current = null;
  };

  const label = {
    idle: unavailableReason ? "Voice unavailable" : "Record a note",
    requesting: "Waiting for microphone\u2026",
    recording: `Stop (${(elapsed / 1000).toFixed(1)} s)`,
    transcribing: "Transcribing your recording\u2026",
  }[phase];

  return (
    <>
      <button
        type="button"
        className={`btn btn-secondary ptt ${phase}`}
        disabled={phase === "requesting" || phase === "transcribing" || (phase === "idle" && (disabled || !!unavailableReason))}
        title={unavailableReason ?? (phase === "recording" ? "Click to stop and transcribe" : "Click to start recording")}
        onClick={phase === "recording" ? stop : start}
        aria-live="polite"
      >
        {phase === "recording" ? <span className="rec-dot" aria-hidden /> : <IconMic />}
        {label}
      </button>
      {unavailableReason && phase === "idle" && <span className="muted small">{unavailableReason}</span>}
      {error && (
        <div className="voice-error small" role="alert">
          {error}
        </div>
      )}
    </>
  );
}
