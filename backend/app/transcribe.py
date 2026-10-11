"""Local push-to-talk transcription: browser audio -> ffmpeg (16 kHz mono WAV) -> whisper.cpp.

The transcript is returned for review only; nothing here submits it for extraction.
Only the raw recording of a successful transcription is kept, and only until it is either
attached to a submitted source or discarded.
"""

import json
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from . import config, db
from .config import FFMPEG, WHISPER_CLI, WHISPER_MODEL
from .schemas import Segment, TranscribeOut

router = APIRouter()

_EXTENSIONS = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/wav": ".wav"}
_RECORDING_NAME = re.compile(r"^[0-9a-f]{32}\.(webm|ogg|m4a|wav)$")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MIN_DURATION_MS = 400
# Unreferenced recordings older than this are treated as abandoned by the startup sweep.
ORPHAN_AGE_S = 3600
# Whisper invents words (often "You") for silent input, so silent recordings are rejected before transcription.
SILENCE_PEAK_DB = -40.0
# Whisper's markers for non-speech audio, e.g. [BLANK_AUDIO], [MUSIC], (silence).
_NON_SPEECH = re.compile(r"\[[^\]]*\]|\((?:silence|music|noise|inaudible|blank[^)]*)\)", re.IGNORECASE)


def audio_dir() -> Path:
    return config.AUDIO_DIR


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"{Path(cmd[0]).name} timed out after {timeout:.0f} s")
    if proc.returncode != 0:
        raise HTTPException(500, f"{Path(cmd[0]).name} failed: {proc.stderr.strip()[-400:] or 'no error output'}")
    return proc


def _peak_db(wav_path: Path) -> float | None:
    proc = _run([FFMPEG, "-hide_banner", "-nostats", "-i", str(wav_path), "-af", "volumedetect", "-f", "null", "-"], timeout=30)
    match = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", proc.stderr)
    if not match:
        return None
    return float("-inf") if match.group(1) == "-inf" else float(match.group(1))


def _remove_conversion_files(stem: Path, keep: Path) -> None:
    """Delete the WAV and whisper outputs for one upload; only the raw recording may remain."""
    for path in stem.parent.glob(f"{stem.name}.*"):
        if path != keep:
            path.unlink(missing_ok=True)


def recording_path(name_or_path: str) -> Path:
    """Resolve a client-supplied recording reference to a file inside the audio folder, or raise ValueError."""
    name = Path(name_or_path).name
    if not _RECORDING_NAME.match(name):
        raise ValueError("not a stored recording")
    path = (audio_dir() / name).resolve()
    if path.parent != audio_dir().resolve():
        raise ValueError("recording is outside the audio folder")
    return path


def sweep_orphans(conn: sqlite3.Connection, older_than_s: float = ORPHAN_AGE_S) -> list[str]:
    """Delete recordings (and stray conversion files) not attached to any source. Returns removed names."""
    folder = audio_dir()
    if not folder.exists():
        return []
    keep = db.referenced_audio_names(conn)
    cutoff = time.time() - older_than_s
    removed = []
    for path in folder.iterdir():
        if path.is_file() and path.name not in keep and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed.append(path.name)
    return removed


@router.post("/api/transcribe", response_model=TranscribeOut)
def transcribe(audio: UploadFile = File(...)) -> TranscribeOut:
    if shutil.which(FFMPEG) is None:
        raise HTTPException(503, "ffmpeg is not installed (brew install ffmpeg)")
    if shutil.which(WHISPER_CLI) is None:
        raise HTTPException(503, "whisper.cpp is not installed (brew install whisper-cpp)")
    if not WHISPER_MODEL.exists():
        raise HTTPException(503, f"Speech model missing at {WHISPER_MODEL}")

    data = audio.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(422, "The recording is empty. Nothing was transcribed.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The recording is too large (limit 25 MB).")

    folder = audio_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / uuid.uuid4().hex
    content_type = (audio.content_type or "").split(";")[0]
    raw_path = stem.with_suffix(_EXTENSIONS.get(content_type, ".webm"))
    try:
        raw_path.write_bytes(data)
        return _transcribe_file(stem, raw_path)
    except BaseException:
        raw_path.unlink(missing_ok=True)
        raise
    finally:
        _remove_conversion_files(stem, keep=raw_path)


def _transcribe_file(stem: Path, raw_path: Path) -> TranscribeOut:
    wav_path = stem.with_suffix(".wav")
    json_path = stem.with_suffix(".json")

    start = time.perf_counter()
    _run([FFMPEG, "-y", "-loglevel", "error", "-i", str(raw_path), "-ar", "16000", "-ac", "1",
          "-c:a", "pcm_s16le", str(wav_path)], timeout=60)
    duration_ms = max(0, wav_path.stat().st_size - 44) / 32  # 16 kHz * 2 bytes per sample
    if duration_ms < MIN_DURATION_MS:
        raise HTTPException(422, f"The recording is too short ({duration_ms:.0f} ms). Record at least half a second.")
    peak = _peak_db(wav_path)
    convert_ms = (time.perf_counter() - start) * 1000
    if peak is not None and peak < SILENCE_PEAK_DB:
        raise HTTPException(
            422,
            f"No speech detected (peak level {peak:.0f} dB). Check that the right microphone is selected and not muted.",
        )

    start = time.perf_counter()
    _run([WHISPER_CLI, "-m", str(WHISPER_MODEL), "-f", str(wav_path), "-l", "en", "-np",
          "-oj", "-of", str(stem)], timeout=180)
    whisper_ms = (time.perf_counter() - start) * 1000
    try:
        result = json.loads(json_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"whisper.cpp produced no readable transcript: {e}")

    segments = []
    for s in result.get("transcription", []):
        text = " ".join(_NON_SPEECH.sub(" ", s.get("text", "")).split())
        if text:
            segments.append(Segment(start_ms=s["offsets"]["from"], end_ms=s["offsets"]["to"], text=text))
    if not segments:
        raise HTTPException(422, "No speech was recognized in the recording. Nothing was transcribed.")

    return TranscribeOut(
        text=" ".join(s.text for s in segments),
        segments=segments,
        audio_path=str(raw_path),
        duration_ms=round(duration_ms),
        peak_db=peak,
        convert_ms=round(convert_ms, 1),
        whisper_ms=round(whisper_ms, 1),
        wall_ms=round(convert_ms + whisper_ms, 1),
        model=WHISPER_MODEL.name,
    )


@router.post("/api/recordings/{name}/discard", status_code=204)
def discard_recording(name: str, conn: sqlite3.Connection = Depends(db.get_conn)) -> Response:
    """Delete a reviewed-but-not-submitted recording. Audio attached to a submitted source is kept."""
    try:
        path = recording_path(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if path.name in db.referenced_audio_names(conn):
        raise HTTPException(409, "This recording belongs to a submitted source and is kept as evidence.")
    if not path.exists():
        raise HTTPException(404, "Recording not found (already discarded or cleaned up).")
    path.unlink()
    return Response(status_code=204)
