"""Photo attachment checks. Images are stored locally; the model is not used except where noted."""

import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import UploadFile
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, photos, pipeline, report  # noqa: E402
from app.photos import CAPTION_NOTE  # noqa: E402
from app.schemas import ObservationIn  # noqa: E402
from test_state import P  # noqa: E402
from app import state  # noqa: E402


def mini_png() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c49444154789c6360f8cffff0000005000101e2d15d2a0000000049454e44ae426082"
    )


def mini_jpeg() -> bytes:
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def _upload(data: bytes, name: str, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers={"content-type": content_type})


class InspectTest(unittest.TestCase):
    def test_png_and_jpeg_are_accepted(self):
        self.assertEqual(photos.inspect_image(mini_png())[0], "png")
        self.assertEqual(photos.inspect_image(mini_jpeg())[0], "jpg")

    def test_spoofed_extension_is_rejected(self):
        with self.assertRaises(ValueError):
            photos.inspect_image(b"this is not an image")
        with self.assertRaises(ValueError):
            photos.inspect_image(b"\xff\xd8\xff not a jpeg frame")


class PhotoApiTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from app import main

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._photo = config.PHOTO_DIR
        config.PHOTO_DIR = self.dir / "photos"
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

    def tearDown(self):
        self.main.app.dependency_overrides.clear()
        config.PHOTO_DIR = self._photo
        self.tmp.cleanup()

    def _job(self) -> int:
        return self.client.post("/api/jobs", json={"title": "photo"}).json()["job"]["id"]

    def test_png_saves_and_is_job_scoped(self):
        jid = self._job()
        r = self.client.post(
            f"/api/jobs/{jid}/photos",
            files={"photo": ("a.png", mini_png(), "image/png")},
            data={"caption": ""},
        )
        self.assertEqual(r.status_code, 200, r.text)
        st = r.json()
        src = st["sources"][0]
        self.assertEqual(src["kind"], "photo")
        self.assertTrue(src["photo_path"])
        self.assertEqual(src["text"], "")
        self.assertEqual([f for f in st["facts"] if f["active"]], [])
        name = src["photo_path"]
        got = self.client.get(f"/api/jobs/{jid}/photos/{name}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, mini_png())
        other = self.client.post("/api/jobs", json={"title": "other"}).json()["job"]["id"]
        self.assertEqual(self.client.get(f"/api/jobs/{other}/photos/{name}").status_code, 404)

    def test_invalid_and_oversized_files_are_rejected(self):
        jid = self._job()
        bad = self.client.post(
            f"/api/jobs/{jid}/photos",
            files={"photo": ("x.jpg", b"not-an-image", "image/jpeg")},
        )
        self.assertEqual(bad.status_code, 422)
        huge = b"\xff\xd8\xff" + b"\x00" * (photos.MAX_PHOTO_BYTES)
        big = self.client.post(
            f"/api/jobs/{jid}/photos",
            files={"photo": ("big.jpg", huge, "image/jpeg")},
        )
        self.assertEqual(big.status_code, 413)
        self.assertEqual(list(config.PHOTO_DIR.glob("*")) if config.PHOTO_DIR.exists() else [], [])

    def test_photo_without_caption_never_completes_work(self):
        conn = db.connect(self.db_path)
        job = db.create_job(conn, "t")
        name = photos.save_upload(_upload(mini_jpeg(), "a.jpg", "image/jpeg"))
        st = pipeline.add_observation(conn, job, ObservationIn(kind="photo", photo_path=name, text=""))
        self.assertEqual(st.facts, [])
        self.assertTrue(all(s.status in ("not_recorded", "not_applicable") for s in st.checklist))
        conn.close()

    def test_html_export_embeds_photo_and_json_has_ids(self):
        conn = db.connect(self.db_path)
        job = db.create_job(conn, "t")
        name = photos.save_upload(_upload(mini_png(), "a.png", "image/png"))
        src = db.insert_source(conn, job, "photo", "Nameplate on unit EF-8", photo_path=name)
        state.apply_extraction(conn, job, src, [P("asset_id", "observed", "unit EF-8", value="EF-8")])
        conn.commit()
        st = pipeline.build_state(conn, job)
        html = report.render_html(st)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("Nameplate on unit EF-8", html)
        self.assertIn("not interpreted by the model", html)
        self.assertIn("not visual analysis", html)
        payload = report.build_json(st)
        self.assertEqual(payload["sources"][0]["photo_id"], name)
        self.assertEqual(payload["sources"][0]["caption"], "Nameplate on unit EF-8")
        fact = payload["asset"][0]
        self.assertTrue(fact["evidence"]["from_caption"])
        self.assertIn(CAPTION_NOTE, st.facts[0].note)
        conn.close()

    def test_handoff_export_keeps_open_work_and_does_not_change_facts(self):
        conn = db.connect(self.db_path)
        job = db.create_job(conn, "t")
        name = photos.save_upload(_upload(mini_png(), "a.png", "image/png"))
        src = db.insert_source(conn, job, "photo", "Leak at the drain valve. I'll test later.", photo_path=name)
        state.apply_extraction(conn, job, src, [
            P("issue", "unresolved", "Leak at the drain valve", item="slow leak"),
            P("final_test", "planned", "I'll test later"),
        ])
        conn.commit()
        before = [(f.id, f.field, f.state, f.review_status) for f in pipeline.build_state(conn, job).facts if f.active]
        conn.close()
        html = self.client.get(f"/api/jobs/{job}/report.html", params={"mode": "handoff", "note": "Return with a new gasket."})
        self.assertEqual(html.status_code, 200)
        self.assertIn("Handoff — work remains", html.text)
        self.assertIn("Return with a new gasket.", html.text)
        self.assertIn("data:image/png;base64,", html.text)
        self.assertIn("saved locally", html.text)
        self.assertIn("@media print", html.text)
        self.assertIn("page-break-inside: avoid", html.text)
        self.assertIn("slow leak", html.text)
        payload = self.client.get(f"/api/jobs/{job}/report.json", params={"mode": "handoff", "note": "Return with a new gasket."}).json()
        self.assertEqual(payload["report_kind"], "handoff")
        self.assertEqual(payload["handoff_note"], "Return with a new gasket.")
        self.assertTrue(payload["saved_locally"])
        self.assertEqual(payload["sources"][0]["photo_id"], name)
        self.assertEqual(payload["unresolved_issues"][0]["item"], "slow leak")
        again = self.client.get(f"/api/jobs/{job}").json()
        after = [(f["id"], f["field"], f["state"], f["review_status"]) for f in again["facts"] if f["active"]]
        self.assertEqual(after, before)
        self.assertEqual(self.client.get(f"/api/jobs/{job}/report.html", params={"mode": "nope"}).status_code, 400)

    def test_handoff_note_is_job_scoped_and_used_in_export(self):
        jid = self._job()
        other = self._job()
        before = self.client.get(f"/api/jobs/{jid}").json()
        facts_before = [(f["id"], f["field"], f["state"], f["review_status"]) for f in before["facts"]]
        saved = self.client.patch(f"/api/jobs/{jid}/handoff", json={"note": "Bring a new gasket."})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["job"]["handoff_note"], "Bring a new gasket.")
        self.assertEqual(
            [(f["id"], f["field"], f["state"], f["review_status"]) for f in saved.json()["facts"]],
            facts_before,
        )
        reloaded = self.client.get(f"/api/jobs/{jid}").json()
        self.assertEqual(reloaded["job"]["handoff_note"], "Bring a new gasket.")
        self.assertEqual(
            [(f["id"], f["field"], f["state"], f["review_status"]) for f in reloaded["facts"]],
            facts_before,
        )
        self.assertIn(self.client.get(f"/api/jobs/{other}").json()["job"]["handoff_note"], (None, ""))
        html = self.client.get(f"/api/jobs/{jid}/report.html", params={"mode": "handoff"})
        self.assertIn("Bring a new gasket.", html.text)
        payload = self.client.get(f"/api/jobs/{jid}/report.json", params={"mode": "handoff"}).json()
        self.assertEqual(payload["handoff_note"], "Bring a new gasket.")
        self.assertEqual(payload["job"]["handoff_note"], "Bring a new gasket.")
        later = self.client.patch(f"/api/jobs/{jid}/handoff", json={"note": "Updated: two gaskets."})
        self.assertEqual(later.status_code, 200)
        latest = self.client.get(f"/api/jobs/{jid}/report.json", params={"mode": "handoff"}).json()
        self.assertEqual(latest["handoff_note"], "Updated: two gaskets.")
        self.assertNotIn("Bring a new gasket.", latest["handoff_note"])
        self.assertEqual(self.client.patch("/api/jobs/999999/handoff", json={"note": "x"}).status_code, 404)

    def test_reload_keeps_the_photo_on_the_same_job(self):
        jid = self._job()
        st = self.client.post(
            f"/api/jobs/{jid}/photos",
            files={"photo": ("a.jpg", mini_jpeg(), "image/jpeg")},
            data={"caption": ""},
        ).json()
        name = st["sources"][0]["photo_path"]
        again = self.client.get(f"/api/jobs/{jid}").json()
        self.assertEqual(again["sources"][0]["photo_path"], name)
        self.assertEqual(again["sources"][0]["kind"], "photo")
        self.assertEqual(self.client.get(f"/api/jobs/{jid}/photos/{name}").status_code, 200)


class HandoffNoteMigrationTest(unittest.TestCase):
    def test_existing_jobs_table_gains_handoff_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL)")
            old.execute("INSERT INTO jobs (title, created_at) VALUES ('legacy', '2026-01-01T00:00:00+00:00')")
            old.commit()
            old.close()
            conn = db.connect(path)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
            self.assertIn("handoff_note", cols)
            job = db.get_job(conn, 1)
            self.assertIsNotNone(job)
            self.assertIsNone(job.handoff_note)
            db.set_handoff_note(conn, 1, "Leave the panel off.")
            self.assertEqual(db.get_job(conn, 1).handoff_note, "Leave the panel off.")
            conn.close()


if __name__ == "__main__":
    unittest.main()
