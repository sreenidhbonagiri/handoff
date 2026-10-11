"""Voice-path checks. The transcription tests run the real ffmpeg + whisper.cpp binaries on audio
synthesized with macOS `say`; they are skipped when those tools or the model are missing.
Run: .venv/bin/python -m unittest discover backend/tests"""

import io
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException, UploadFile  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app import config, db, transcribe  # noqa: E402
from app.config import FFMPEG, WHISPER_CLI, WHISPER_MODEL  # noqa: E402
from app.schemas import ObservationIn  # noqa: E402

HAVE_TOOLS = all(shutil.which(t) for t in (FFMPEG, WHISPER_CLI, "say")) and WHISPER_MODEL.exists()


def _assert_ffmpeg_can_read(path: Path, what: str) -> None:
    """Reject stub or header-only files. ffmpeg exits 0 when it muxes an empty WebM."""
    probe = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            f"{what} is not readable audio ({path.stat().st_size} bytes): {probe.stderr.strip()[-300:]}"
        )


def _spoken_wav(tmp: Path, name: str, text: str) -> Path:
    """Synthesize speech to PCM WAV. AIFF-C from `say -o *.aiff` is a 4 KB stub in some sandboxes."""
    wav = tmp / f"{name}.wav"
    subprocess.run(["say", "-o", str(wav), "--data-format=LEI16@22050", text], check=True)
    if wav.stat().st_size < 8000:
        raise RuntimeError(
            f"say wrote a stub WAV ({wav.stat().st_size} bytes). Speech synthesis must be able to write audio."
        )
    _assert_ffmpeg_can_read(wav, "say WAV")
    return wav


def _webm(tmp: Path, name: str, ffmpeg_input: list[str]) -> bytes:
    out = tmp / f"{name}.webm"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", *ffmpeg_input, "-f", "webm", "-c:a", "libopus", "-application", "voip", str(out)],
        check=True,
    )
    _assert_ffmpeg_can_read(out, "generated WebM")
    return out.read_bytes()


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="note.webm", headers={"content-type": "audio/webm"})


@unittest.skipUnless(HAVE_TOOLS, "ffmpeg, whisper-cli, say, or the whisper model is missing")
class TranscribeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._audio_dir = config.AUDIO_DIR
        config.AUDIO_DIR = self.dir / "audio"

    def tearDown(self):
        config.AUDIO_DIR = self._audio_dir
        self.tmp.cleanup()

    def files(self):
        return sorted(p.name for p in config.AUDIO_DIR.iterdir()) if config.AUDIO_DIR.exists() else []

    def test_speech_is_transcribed_with_separate_timings(self):
        wav = _spoken_wav(self.dir, "speech", "Replaced the drive belt. The bearing is still squealing.")
        out = transcribe.transcribe(_upload(_webm(self.dir, "speech", ["-i", str(wav)])))
        self.assertIn("belt", out.text.lower())
        self.assertGreater(out.whisper_ms, 0)
        self.assertGreater(out.convert_ms, 0)
        self.assertAlmostEqual(out.wall_ms, out.convert_ms + out.whisper_ms, delta=1)
        self.assertTrue(Path(out.audio_path).exists())
        # Only the raw recording survives; the WAV and whisper JSON are removed.
        self.assertEqual(self.files(), [Path(out.audio_path).name])

    def test_silence_is_rejected_not_hallucinated(self):
        data = _webm(self.dir, "silence", ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "2"])
        with self.assertRaises(HTTPException) as ctx:
            transcribe.transcribe(_upload(data))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("No speech detected", ctx.exception.detail)
        self.assertEqual(self.files(), [])

    def test_too_short_is_rejected(self):
        data = _webm(self.dir, "short", ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.1"])
        with self.assertRaises(HTTPException) as ctx:
            transcribe.transcribe(_upload(data))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.files(), [])

    def test_empty_upload_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            transcribe.transcribe(_upload(b""))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.files(), [])

    def test_garbage_upload_reports_ffmpeg_failure(self):
        with self.assertRaises(HTTPException) as ctx:
            transcribe.transcribe(_upload(b"not audio at all"))
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("ffmpeg failed", ctx.exception.detail)
        self.assertEqual(self.files(), [])

    def test_whisper_failure_removes_all_files(self):
        wav = _spoken_wav(self.dir, "speech", "Tightened the mounting bolts.")
        data = _webm(self.dir, "speech", ["-i", str(wav)])
        original_model = transcribe.WHISPER_MODEL
        broken = self.dir / "broken-model.bin"
        broken.write_bytes(b"not a model")
        transcribe.WHISPER_MODEL = broken
        try:
            with self.assertRaises(HTTPException) as ctx:
                transcribe.transcribe(_upload(data))
        finally:
            transcribe.WHISPER_MODEL = original_model
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(self.files(), [])

    def test_unexpected_error_removes_all_files(self):
        original = transcribe._transcribe_file

        def explode(stem, raw_path):
            stem.with_suffix(".wav").write_bytes(b"partial")
            raise RuntimeError("simulated crash mid-conversion")

        transcribe._transcribe_file = explode
        try:
            with self.assertRaises(RuntimeError):
                transcribe.transcribe(_upload(b"some bytes"))
        finally:
            transcribe._transcribe_file = original
        self.assertEqual(self.files(), [])


@unittest.skipUnless(HAVE_TOOLS, "ffmpeg, whisper-cli, say, or the whisper model is missing")
class RecordingCleanupApiTest(unittest.TestCase):
    """Discard, keep-on-submit, and sweep through the HTTP API with a temporary DB and audio folder."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from app import main

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._audio_dir = config.AUDIO_DIR
        config.AUDIO_DIR = self.dir / "audio"
        self.db_path = self.dir / "t.db"

        def conn_override():
            conn = db.connect(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

        main.app.dependency_overrides[db.get_conn] = conn_override
        self.main = main
        self.client = TestClient(main.app)
        wav = _spoken_wav(self.dir, "speech", "Replaced the drive belt.")
        self.speech = _webm(self.dir, "speech", ["-i", str(wav)])

    def tearDown(self):
        self.main.app.dependency_overrides.clear()
        config.AUDIO_DIR = self._audio_dir
        self.tmp.cleanup()

    def files(self):
        return sorted(p.name for p in config.AUDIO_DIR.iterdir()) if config.AUDIO_DIR.exists() else []

    def transcribe(self):
        r = self.client.post("/api/transcribe", files={"audio": ("n.webm", self.speech, "audio/webm")})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_discard_deletes_pending_recording(self):
        out = self.transcribe()
        name = Path(out["audio_path"]).name
        self.assertEqual(self.files(), [name])
        self.assertEqual(self.client.post(f"/api/recordings/{name}/discard").status_code, 204)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.client.post(f"/api/recordings/{name}/discard").status_code, 404)

    def test_submitted_recording_is_kept(self):
        out = self.transcribe()
        name = Path(out["audio_path"]).name
        conn = db.connect(self.db_path)
        job = db.create_job(conn, "keep")
        db.insert_source(conn, job, "voice", out["text"], audio_path=out["audio_path"], original_transcript=out["text"])
        conn.commit()
        r = self.client.post(f"/api/recordings/{name}/discard")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.files(), [name])
        self.assertEqual(transcribe.sweep_orphans(conn, older_than_s=0), [])
        self.assertEqual(self.files(), [name])
        conn.close()

    def test_discard_rejects_paths_outside_audio_folder(self):
        outside = self.dir / "keep-me.txt"
        outside.write_text("x")
        for bad in ["..%2Fkeep-me.txt", "keep-me.txt", "not-a-recording.webm"]:
            r = self.client.post(f"/api/recordings/{bad}/discard")
            self.assertGreaterEqual(r.status_code, 400, bad)
        conn = db.connect(self.db_path)
        for bad in ["../keep-me.txt", str(outside), "keep-me.txt"]:
            with self.assertRaises(HTTPException) as ctx:
                transcribe.discard_recording(bad, conn)
            self.assertEqual(ctx.exception.status_code, 400, bad)
        conn.close()
        self.assertTrue(outside.exists())

    def test_sweep_removes_only_old_unreferenced_files(self):
        old = self.transcribe()
        recent = self.transcribe()
        conn = db.connect(self.db_path)
        old_path = Path(old["audio_path"])
        stamp = old_path.stat().st_mtime - 7200
        import os

        os.utime(old_path, (stamp, stamp))
        removed = transcribe.sweep_orphans(conn)
        conn.close()
        self.assertEqual(removed, [old_path.name])
        self.assertEqual(self.files(), [Path(recent["audio_path"]).name])

    def test_submission_with_missing_recording_is_rejected(self):
        conn = db.connect(self.db_path)
        job = db.create_job(conn, "missing")
        conn.close()
        r = self.client.post(f"/api/jobs/{job}/observations", json={
            "text": "Replaced the drive belt.", "kind": "voice", "original_transcript": "Replaced the drive belt.",
            "audio_path": str(config.AUDIO_DIR / ("0" * 32 + ".webm")),
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("no longer available", r.json()["detail"])
        r = self.client.post(f"/api/jobs/{job}/observations", json={
            "text": "x", "kind": "voice", "original_transcript": "x", "audio_path": "/etc/passwd",
        })
        self.assertEqual(r.status_code, 400)


class VoiceObservationTest(unittest.TestCase):
    def test_voice_requires_original_transcript(self):
        with self.assertRaises(ValidationError):
            ObservationIn(text="Replaced a belt.", kind="voice")
        ObservationIn(text="Replaced a belt.", kind="voice", original_transcript="Replace a belt.")

    def test_blank_text_rejected(self):
        with self.assertRaises(ValidationError):
            ObservationIn(text="   ", kind="typed")

    def test_original_and_reviewed_transcripts_both_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "t.db")
            job = db.create_job(conn, "voice")
            src = db.insert_source(conn, job, "voice", "Unit FP-017. Replaced two filters.",
                                   original_transcript="Unit FP017. Replace two filters.", transcription_ms=512.0)
            self.assertEqual(src.text, "Unit FP-017. Replaced two filters.")
            self.assertEqual(src.original_transcript, "Unit FP017. Replace two filters.")
            self.assertEqual(src.transcription_ms, 512.0)
            self.assertIsNone(src.extraction_ms)
            conn.close()

    def test_existing_database_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, job_id INTEGER, kind TEXT, text TEXT, created_at TEXT,"
                        " audio_path TEXT, segments_json TEXT, answers_requirement TEXT, revises INTEGER, replaced_by INTEGER)")
            old.commit()
            old.close()
            conn = db.connect(path)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(sources)")}
            self.assertTrue({"original_transcript", "transcription_ms"} <= cols)
            conn.close()


if __name__ == "__main__":
    unittest.main()
