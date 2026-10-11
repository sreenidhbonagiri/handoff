"""Floor-plan storage, pin coordinates, and pin-status derivation. Images are not sent to the model."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, site_map, state  # noqa: E402
from test_photos import mini_jpeg, mini_png  # noqa: E402
from test_state import P  # noqa: E402


def _upload(data: bytes, name: str = "plan.png", content_type: str = "image/png") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers={"content-type": content_type})


def huge_png() -> bytes:
    data = bytearray(mini_png())
    data[16:20] = (5000).to_bytes(4, "big")
    data[20:24] = (5000).to_bytes(4, "big")
    return bytes(data)


class CoordTest(unittest.TestCase):
    def test_accepts_unit_square(self):
        self.assertEqual(site_map.validate_coords(0, 1), (0.0, 1.0))
        self.assertEqual(site_map.validate_coords(0.25, 0.75), (0.25, 0.75))

    def test_rejects_outside_and_nan(self):
        for x, y in ((-0.01, 0.5), (1.01, 0.2), (0.2, 2), (float("nan"), 0.1)):
            with self.assertRaises(ValueError):
                site_map.validate_coords(x, y)


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _job(self, title="map job"):
        return db.create_job(self.conn, title)

    def _facts(self, job_id, text, proposals):
        src = db.insert_source(self.conn, job_id, "typed", text)
        state.apply_extraction(self.conn, job_id, src, proposals)
        self.conn.commit()
        return db.get_job(self.conn, job_id)

    def test_empty_job_is_needs_attention(self):
        job = db.get_job(self.conn, self._job("Map empty"))
        item = site_map.map_job_item(self.conn, job)
        self.assertEqual(item.status, "needs_attention")
        self.assertTrue(any(r.status == "not_recorded" for r in item.checklist or []))

    def test_unresolved_issue_and_planned_test_is_open_problem(self):
        job = self._facts(
            self._job("Map leak planned"),
            "There is a leak. I'll test later.",
            [
                P("issue", "unresolved", "There is a leak", item="leak"),
                P("final_test", "planned", "I'll test later"),
            ],
        )
        item = site_map.map_job_item(self.conn, job)
        self.assertEqual(item.status, "open_problem")
        self.assertGreater(len(site_map.unresolved_issues(item.facts)), 0)
        self.assertGreater(len(site_map.open_checks(item.checklist or [])), 0)

    def test_passed_test_does_not_hide_unresolved_issue(self):
        job = self._facts(
            self._job("Map leak passed"),
            "Leak still open. Final test passed.",
            [
                P("issue", "unresolved", "Leak still open", item="leak"),
                P("final_test", "reported_complete", "Final test passed", value="passed"),
            ],
        )
        item = site_map.map_job_item(self.conn, job)
        self.assertEqual(item.status, "open_problem")

    def test_pending_review_is_needs_attention(self):
        job_id = self._job("Map pending")
        job = self._facts(
            job_id,
            "Replaced two filters—actually maybe three.",
            [P(
                "part_replaced", "reported_complete", "Replaced two filters—actually maybe three",
                item="filters", value="2", corrects="two filters",
            )],
        )
        facts = [f for f in db.list_facts(self.conn, job_id) if f.active]
        if not any(f.review_status in ("needs_review", "conflicting") for f in facts):
            db.update_fact(self.conn, facts[0].id, review_status="needs_review")
            self.conn.commit()
            job = db.get_job(self.conn, job_id)
        item = site_map.map_job_item(self.conn, job)
        self.assertEqual(item.status, "needs_attention")

    def test_issue_and_pending_review_stays_open_problem(self):
        job_id = self._job("Map both")
        job = self._facts(
            job_id,
            "Leak at the coil. Replaced two filters—actually three.",
            [
                P("issue", "unresolved", "Leak at the coil", item="leak"),
                P(
                    "part_replaced", "reported_complete", "Replaced two filters—actually three",
                    item="filters", value="2", corrects="two filters",
                ),
            ],
        )
        facts = [f for f in db.list_facts(self.conn, job_id) if f.active]
        pending = next((f for f in facts if f.field == "part_replaced"), facts[0])
        db.update_fact(self.conn, pending.id, review_status="needs_review")
        self.conn.commit()
        item = site_map.map_job_item(self.conn, db.get_job(self.conn, job_id))
        self.assertEqual(item.status, "open_problem")
        self.assertGreater(len(site_map.unresolved_issues(item.facts)), 0)
        self.assertGreater(len(site_map.pending_facts(item.facts)), 0)

    def test_evaluate_failure_is_unavailable(self):
        job = db.get_job(self.conn, self._job("Map status fail"))
        with patch("app.site_map.checklist.evaluate", side_effect=RuntimeError("boom")):
            item = site_map.map_job_item(self.conn, job)
        self.assertIsNone(item.status)
        self.assertEqual(item.status_error, "Status unavailable.")
        self.assertIsNone(item.checklist)


class SiteMapApiTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from app import main

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._site = config.SITE_DIR
        config.SITE_DIR = self.dir / "site"
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
        config.SITE_DIR = self._site
        self.tmp.cleanup()

    def _job(self, title="Map persist", location="Roof unit"):
        return self.client.post("/api/jobs", json={"title": title, "location": location}).json()["job"]["id"]

    def _plan(self, name="Building B", confirm=False, data=None, filename="plan.png"):
        files = {"plan": (filename, data or mini_png(), "image/png")}
        form = {"name": name, "confirm_replace": "true" if confirm else "false"}
        return self.client.post("/api/site-map", files=files, data=form)

    def test_invalid_upload_is_rejected(self):
        resp = self._plan(data=b"not an image", filename="plan.png")
        self.assertEqual(resp.status_code, 422)

    def test_oversized_file_is_rejected(self):
        resp = self._plan(data=b"\x89PNG\r\n\x1a\n" + b"x" * (8 * 1024 * 1024), filename="plan.png")
        self.assertEqual(resp.status_code, 413)

    def test_pixel_limit_is_rejected(self):
        resp = self._plan(data=huge_png())
        self.assertEqual(resp.status_code, 422)
        self.assertIn("pixels", resp.json()["detail"])

    def test_jpeg_upload_and_image_persist(self):
        resp = self.client.post(
            "/api/site-map",
            files={"plan": ("plan.jpg", mini_jpeg(), "image/jpeg")},
            data={"name": "Yard", "confirm_replace": "false"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["plan"]["name"], "Yard")
        image = self.client.get("/api/site-map/image")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/jpeg")

    def test_pin_persists_and_does_not_change_job(self):
        jid = self._job("Map persist job", "Mechanical room")
        conn = db.connect(self.db_path)
        db.insert_source(conn, jid, "typed", "Map persist source note.")
        conn.commit()
        conn.close()
        before = self.client.get(f"/api/jobs/{jid}").json()
        self.assertEqual(self._plan().status_code, 200)
        placed = self.client.post("/api/site-map/pins", json={"job_id": jid, "x": 0.25, "y": 0.8})
        self.assertEqual(placed.status_code, 200)
        state = self.client.get("/api/site-map").json()
        pin = next(j["pin"] for j in state["jobs"] if j["job"]["id"] == jid)
        self.assertEqual((pin["x"], pin["y"]), (0.25, 0.8))
        after = self.client.get(f"/api/jobs/{jid}").json()
        self.assertEqual(after["job"]["location"], "Mechanical room")
        self.assertEqual(after["job"]["updated_at"], before["job"]["updated_at"])
        self.assertEqual(
            [(s["id"], s["text"]) for s in after["sources"]],
            [(s["id"], s["text"]) for s in before["sources"]],
        )

    def test_reposition_and_remove_keep_job(self):
        jid = self._job("Map move job")
        self._plan()
        self.client.post("/api/site-map/pins", json={"job_id": jid, "x": 0.1, "y": 0.1})
        moved = self.client.patch(f"/api/site-map/pins/{jid}", json={"x": 0.9, "y": 0.4})
        self.assertEqual(moved.status_code, 200)
        self.assertEqual((moved.json()["x"], moved.json()["y"]), (0.9, 0.4))
        removed = self.client.delete(f"/api/site-map/pins/{jid}")
        self.assertEqual(removed.status_code, 200)
        job = self.client.get(f"/api/jobs/{jid}")
        self.assertEqual(job.status_code, 200)
        self.assertEqual(job.json()["job"]["title"], "Map move job")
        state = self.client.get("/api/site-map").json()
        self.assertIsNone(next(j["pin"] for j in state["jobs"] if j["job"]["id"] == jid))

    def test_replace_plan_requires_confirmation_and_clears_pins(self):
        jid = self._job("Map replace job")
        self.assertEqual(self._plan().status_code, 200)
        self.client.post("/api/site-map/pins", json={"job_id": jid, "x": 0.5, "y": 0.5})
        blocked = self._plan(name="New plan")
        self.assertEqual(blocked.status_code, 409)
        still = self.client.get("/api/site-map").json()
        self.assertIsNotNone(next(j["pin"] for j in still["jobs"] if j["job"]["id"] == jid))
        cleared = self._plan(name="New plan", confirm=True)
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["plan"]["name"], "New plan")
        self.assertIsNone(next(j["pin"] for j in cleared.json()["jobs"] if j["job"]["id"] == jid))

    def test_bad_coordinates_are_rejected(self):
        jid = self._job("Map coord job")
        self._plan()
        resp = self.client.post("/api/site-map/pins", json={"job_id": jid, "x": 1.2, "y": 0.2})
        self.assertEqual(resp.status_code, 400)

    def test_empty_job_status_on_map(self):
        jid = self._job("Map empty api")
        self._plan()
        item = next(j for j in self.client.get("/api/site-map").json()["jobs"] if j["job"]["id"] == jid)
        self.assertEqual(item["status"], "needs_attention")


if __name__ == "__main__":
    unittest.main()
