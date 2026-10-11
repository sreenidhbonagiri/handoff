"""Dashboard job list, title/location, and migration. Existing rows keep their IDs."""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, main, pipeline, state  # noqa: E402
from test_state import P  # noqa: E402


class JobDashboardApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "t.db"

        def conn_override():
            conn = db.connect(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

        main.app.dependency_overrides[db.get_conn] = conn_override
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.tmp.cleanup()

    def test_list_is_empty_then_includes_saved_jobs_only(self):
        self.assertEqual(self.client.get("/api/jobs").json(), [])
        created = self.client.post("/api/jobs", json={"title": "Rooftop visit", "location": "Building B"}).json()
        listed = self.client.get("/api/jobs").json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["job"]["id"], created["job"]["id"])
        self.assertEqual(listed[0]["job"]["title"], "Rooftop visit")
        self.assertEqual(listed[0]["job"]["location"], "Building B")
        self.assertEqual(listed[0]["facts"], [])
        self.assertTrue(listed[0]["job"]["updated_at"])

    def test_blank_title_and_location_are_allowed(self):
        st = self.client.post("/api/jobs", json={}).json()
        self.assertEqual(st["job"]["title"], "")
        self.assertIsNone(st["job"]["location"])
        self.assertEqual(st["sources"], [])
        self.assertEqual(st["facts"], [])

    def test_patch_title_and_location_does_not_change_facts(self):
        jid = self.client.post("/api/jobs", json={"title": "A"}).json()["job"]["id"]
        conn = db.connect(self.db_path)
        src = db.insert_source(conn, jid, "typed", "Unit RT-9. Leak at the valve.")
        state.apply_extraction(conn, jid, src, [
            P("asset_id", "observed", "Unit RT-9", value="RT-9"),
            P("issue", "unresolved", "Leak at the valve", item="slow leak"),
        ])
        conn.commit()
        before = [(f.id, f.field, f.state, f.review_status) for f in pipeline.build_state(conn, jid).facts if f.active]
        conn.close()
        patched = self.client.patch(f"/api/jobs/{jid}", json={"title": "RT-9 service", "location": "Roof"}).json()
        self.assertEqual(patched["job"]["title"], "RT-9 service")
        self.assertEqual(patched["job"]["location"], "Roof")
        after = [(f["id"], f["field"], f["state"], f["review_status"]) for f in patched["facts"] if f["active"]]
        self.assertEqual(after, before)
        listed = self.client.get("/api/jobs").json()
        self.assertEqual(listed[0]["job"]["title"], "RT-9 service")
        self.assertEqual({f["field"] for f in listed[0]["facts"] if f["active"]}, {"asset_id", "issue"})

    def test_two_jobs_keep_separate_notes_facts_and_handoff(self):
        a = self.client.post("/api/jobs", json={"title": "Job A", "location": "North"}).json()["job"]["id"]
        b = self.client.post("/api/jobs", json={"title": "Job B", "location": "South"}).json()["job"]["id"]
        conn = db.connect(self.db_path)
        src_a = db.insert_source(conn, a, "typed", "Unit AA-1")
        src_b = db.insert_source(conn, b, "typed", "Unit BB-2")
        state.apply_extraction(conn, a, src_a, [P("asset_id", "observed", "Unit AA-1", value="AA-1")])
        state.apply_extraction(conn, b, src_b, [P("asset_id", "observed", "Unit BB-2", value="BB-2")])
        conn.commit()
        conn.close()
        self.client.patch(f"/api/jobs/{a}/handoff", json={"note": "Note for A only."})
        self.client.patch(f"/api/jobs/{b}/handoff", json={"note": "Note for B only."})
        sa = self.client.get(f"/api/jobs/{a}").json()
        sb = self.client.get(f"/api/jobs/{b}").json()
        self.assertEqual(sa["job"]["handoff_note"], "Note for A only.")
        self.assertEqual(sb["job"]["handoff_note"], "Note for B only.")
        self.assertEqual(sa["sources"][0]["text"], "Unit AA-1")
        self.assertEqual(sb["sources"][0]["text"], "Unit BB-2")
        self.assertEqual(sa["facts"][0]["value"], "AA-1")
        self.assertEqual(sb["facts"][0]["value"], "BB-2")
        ids = {item["job"]["id"] for item in self.client.get("/api/jobs").json()}
        self.assertEqual(ids, {a, b})

    def test_existing_jobs_keep_ids_and_gain_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            old = sqlite3.connect(path)
            old.execute(
                "CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, handoff_note TEXT)"
            )
            old.execute(
                "INSERT INTO jobs (id, title, created_at, handoff_note) VALUES (7, 'legacy', '2026-01-01T00:00:00+00:00', 'Keep me')"
            )
            old.commit()
            old.close()
            conn = db.connect(path)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
            self.assertIn("location", cols)
            self.assertIn("updated_at", cols)
            job = db.get_job(conn, 7)
            self.assertEqual(job.id, 7)
            self.assertEqual(job.title, "legacy")
            self.assertEqual(job.handoff_note, "Keep me")
            self.assertIsNone(job.location)
            self.assertEqual(job.updated_at, "2026-01-01T00:00:00+00:00")
            conn.close()


if __name__ == "__main__":
    unittest.main()
