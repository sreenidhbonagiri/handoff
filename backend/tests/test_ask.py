"""Read-only job Q&A. The model is mocked except where a test says otherwise."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ask, db, llm, pipeline, state  # noqa: E402
from app.schemas import AskItem  # noqa: E402
from test_state import P  # noqa: E402


def _items(raw_items: list[dict], kind: str = "job") -> str:
    return json.dumps({"kind": kind, "items": raw_items})


def _chat(content: str, wall_ms: float = 12.0):
    def fake(_messages, _schema):
        return llm.ChatResult(content=content, metrics={"wall_ms": wall_ms})

    return fake


class AskLogicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _job(self, title, text=None, proposals=None):
        jid = db.create_job(self.conn, title)
        if text and proposals:
            src = db.insert_source(self.conn, jid, "typed", text)
            state.apply_extraction(self.conn, jid, src, proposals)
            self.conn.commit()
        return jid

    def test_context_is_job_scoped(self):
        a = self._job("Ask A", "Unit AA-1. Replaced two filters.", [
            P("asset_id", "observed", "Unit AA-1", value="AA-1"),
            P("part_replaced", "reported_complete", "Replaced two filters", item="filters", value="2"),
        ])
        b = self._job("Ask B", "Secret note on the other job: leak at coil BB.", [
            P("issue", "unresolved", "leak at coil BB", item="leak"),
        ])
        text, _ = ask.context_from_conn(self.conn, a)
        self.assertIn("AA-1", text)
        self.assertIn("two filters", text)
        self.assertNotIn("Secret note on the other job", text)
        self.assertNotIn("coil BB", text)
        other, _ = ask.context_from_conn(self.conn, b)
        self.assertIn("Secret note on the other job", other)
        self.assertNotIn("AA-1", other)

    def test_pending_and_superseded_are_labeled(self):
        jid = self._job(
            "Ask labels",
            "Replaced two filters—actually three.",
            [P(
                "part_replaced", "reported_complete", "Replaced two filters—actually three",
                item="filters", value="2", corrects="two filters",
            )],
        )
        facts = db.list_facts(self.conn, jid)
        active = [f for f in facts if f.active]
        history = [f for f in facts if f.superseded_by]
        if active:
            db.update_fact(self.conn, active[0].id, review_status="needs_review")
            self.conn.commit()
        text, _ = ask.context_from_conn(self.conn, jid)
        self.assertIn("unconfirmed — awaiting review", text)
        self.assertIn("HISTORY / SUPERSEDED", text)
        if history:
            self.assertIn(f"F{history[0].id}", text)
            self.assertIn("earlier value only", text)

    def test_context_separates_missing_from_explicitly_not_done(self):
        jid = self._job(
            "Ask unfinished split",
            "I haven't run the final test yet.",
            [P("final_test", "explicitly_not_complete", "I haven't run the final test yet")],
        )
        text, _ = ask.context_from_conn(self.conn, jid)
        self.assertIn("MISSING INFORMATION", text)
        self.assertIn("[R1]", text)
        self.assertIn("EXPLICITLY NOT DONE", text)
        self.assertIn("Not done yet", text)

    def test_empty_job_has_not_recorded_checklist(self):
        jid = self._job("Ask empty")
        text, _ = ask.context_from_conn(self.conn, jid)
        self.assertIn("none", text.lower())
        self.assertIn("Not recorded", text)
        self.assertIn("[R1]", text)

    def test_validate_rejects_cross_job_and_unknown_ids(self):
        a = self._job("Ask cite A", "Unit A-1", [P("asset_id", "observed", "Unit A-1", value="A-1")])
        b = self._job("Ask cite B", "Unit B-2", [P("asset_id", "observed", "Unit B-2", value="B-2")])
        st = pipeline.build_state(self.conn, a)
        other = db.list_facts(self.conn, b)[0]
        with self.assertRaises(ValueError):
            ask.validate_items([AskItem(text="other job", fact_ids=[other.id])], st)
        with self.assertRaises(ValueError):
            ask.validate_items([AskItem(text="missing source", source_ids=[99999])], st)
        with self.assertRaises(ValueError):
            ask.validate_items([AskItem(text="no cites")], st)
        own = [f for f in st.facts if f.active][0]
        ask.validate_items([AskItem(text="ok", kind="from_record", fact_ids=[own.id], source_ids=[own.source_id])], st)

    def test_missing_information_allows_only_not_recorded_checklist(self):
        jid = self._job(
            "Ask missing kinds",
            "I haven't run the final test yet.",
            [P("final_test", "explicitly_not_complete", "I haven't run the final test yet")],
        )
        st = pipeline.build_state(self.conn, jid)
        ask.validate_items([AskItem(text="Asset ID is not recorded.", kind="missing_information", requirement_ids=["R1"])], st)
        with self.assertRaises(ValueError):
            ask.validate_items([
                AskItem(text="Asset ID is not recorded.", kind="missing_information", fact_ids=[st.facts[0].id], requirement_ids=["R1"]),
            ], st)
        with self.assertRaises(ValueError):
            ask.validate_items([
                AskItem(text="Asset ID is not recorded.", kind="missing_information", source_ids=[st.sources[0].id], requirement_ids=["R1"]),
            ], st)
        with self.assertRaises(ValueError):
            ask.validate_items([
                AskItem(text="The test is not done.", kind="missing_information", requirement_ids=["R3"]),
            ], st)
        with self.assertRaises(ValueError):
            ask.validate_items([
                AskItem(text="Asset ID is not recorded.", kind="from_record", requirement_ids=["R1"]),
            ], st)
        test_fact = next(f for f in st.facts if f.field == "final_test")
        ask.validate_items([
            AskItem(text="The final test is not done yet.", kind="from_record", fact_ids=[test_fact.id], requirement_ids=["R3"]),
        ], st)

    def test_parse_drops_model_supplied_related_facts(self):
        items = ask._parse_items(_items([{
            "kind": "from_record",
            "text": "Current quantity is 3.",
            "source_ids": [1],
            "fact_ids": [2],
            "requirement_ids": ["R2"],
            "related_fact_ids": [99],
        }]))
        self.assertEqual(items[0].related_fact_ids, [])
        self.assertEqual(items[0].kind, "from_record")
        self.assertEqual(items[0].fact_ids, [2])
        turn, parsed = ask._parse_answer(_items([{
            "kind": "message",
            "text": "Hello.",
            "source_ids": [],
            "fact_ids": [],
            "requirement_ids": [],
        }], kind="greeting"))
        self.assertEqual(turn, "greeting")
        self.assertEqual(parsed[0].kind, "message")

    def test_cite_labels_come_from_saved_facts(self):
        jid = self._job(
            "Ask cite labels",
            "Replaced two filters—actually three.",
            [P(
                "part_replaced", "reported_complete", "Replaced two filters—actually three",
                item="filters", value="2", corrects="two filters",
            )],
        )
        facts = db.list_facts(self.conn, jid)
        history = next(f for f in facts if f.superseded_by)
        current = next(f for f in facts if f.active)
        self.assertEqual(ask.fact_cite_label(history), "Earlier value")
        self.assertIsNone(ask.fact_cite_label(current))
        db.update_fact(self.conn, current.id, review_status="needs_review")
        self.conn.commit()
        pending = next(f for f in db.list_facts(self.conn, jid) if f.id == current.id)
        self.assertEqual(ask.fact_cite_label(pending), "Awaiting confirmation")
        db.update_fact(self.conn, current.id, review_status="conflicting")
        self.conn.commit()
        conflict = next(f for f in db.list_facts(self.conn, jid) if f.id == current.id)
        self.assertEqual(ask.fact_cite_label(conflict), "Awaiting confirmation")

    def test_enrich_attaches_history_and_pending_from_saved_facts(self):
        jid = self._job(
            "Ask enrich",
            "Replaced two filters—actually three.",
            [P(
                "part_replaced", "reported_complete", "Replaced two filters—actually three",
                item="filters", value="2", corrects="two filters",
            )],
        )
        leak_src = db.insert_source(self.conn, jid, "typed", "There is a leak at the coil.")
        state.apply_extraction(self.conn, jid, leak_src, [
            P("issue", "unresolved", "There is a leak at the coil", item="leak"),
        ])
        resolved_src = db.insert_source(self.conn, jid, "typed", "All sorted now.")
        state.apply_extraction(self.conn, jid, resolved_src, [
            P("issue", "resolved", "All sorted now", item="leak"),
        ])
        self.conn.commit()
        facts = db.list_facts(self.conn, jid)
        history = next(f for f in facts if f.field == "part_replaced" and f.superseded_by)
        current = next(f for f in facts if f.field == "part_replaced" and f.active)
        leak_open = next(f for f in facts if f.field == "issue" and f.state == "unresolved" and f.active)
        leak_resolved = next(f for f in facts if f.field == "issue" and f.state == "resolved" and f.active)
        if leak_resolved.review_status not in ("needs_review", "conflicting"):
            db.update_fact(self.conn, leak_resolved.id, review_status="needs_review")
            self.conn.commit()
        st = pipeline.build_state(self.conn, jid)

        quantity = ask.enrich_items([AskItem(text="Current quantity is 3.", kind="from_record", fact_ids=[current.id])], st)
        self.assertEqual(quantity[0].fact_ids, [current.id])
        self.assertEqual(quantity[0].related_fact_ids, [history.id])
        self.assertEqual(ask.fact_cite_label(next(f for f in st.facts if f.id == history.id)), "Earlier value")

        leak = ask.enrich_items([AskItem(text="The leak is still open.", kind="from_record", fact_ids=[leak_open.id])], st)
        self.assertEqual(leak[0].fact_ids, [leak_open.id])
        self.assertEqual(leak[0].related_fact_ids, [leak_resolved.id])
        pending = next(f for f in st.facts if f.id == leak_resolved.id)
        self.assertEqual(ask.fact_cite_label(pending), "Awaiting confirmation")

        from_pending = ask.enrich_items([
            AskItem(text="The leak is reported fixed.", kind="from_record", fact_ids=[leak_resolved.id]),
        ], st)
        self.assertEqual(from_pending[0].fact_ids, [leak_resolved.id])
        self.assertEqual(from_pending[0].related_fact_ids, [leak_open.id])

        untouched = ask.enrich_items([AskItem(text="Asset ID confirmed", kind="missing_information", requirement_ids=["R1"])], st)
        self.assertEqual(untouched[0].fact_ids, [])
        self.assertEqual(untouched[0].related_fact_ids, [])
        self.assertEqual(untouched[0].text, "Equipment ID: not recorded.")
        self.assertNotIn("Asset ID confirmed", untouched[0].text)

    def test_missing_information_uses_checklist_status_wording(self):
        jid = self._job(
            "Ask missing wording",
            "I haven't run the final test yet.",
            [P("final_test", "explicitly_not_complete", "I haven't run the final test yet")],
        )
        st = pipeline.build_state(self.conn, jid)
        presented = ask.enrich_items([
            AskItem(text="Asset ID confirmed", kind="missing_information", requirement_ids=["R1"]),
            AskItem(text="Completed action and parts/quantity recorded", kind="missing_information", requirement_ids=["R2"]),
            AskItem(text="Remaining issue status recorded", kind="missing_information", requirement_ids=["R4"]),
        ], st)
        self.assertEqual([item.text for item in presented], [
            "Equipment ID: not recorded.",
            "Work done and parts used: not recorded.",
            "Remaining problem status: not recorded.",
        ])
        for item in presented:
            self.assertNotIn("confirmed", item.text.lower())
            self.assertNotIn("Asset ID", item.text)

    def test_pending_resolution_does_not_attach_unrelated_issue(self):
        jid = self._job(
            "Ask unrelated issue",
            "There is a leak at the coil. Fan is rattling.",
            [
                P("issue", "unresolved", "There is a leak at the coil", item="leak"),
                P("issue", "unresolved", "Fan is rattling", item="rattling"),
            ],
        )
        resolved_src = db.insert_source(self.conn, jid, "typed", "All sorted now.")
        state.apply_extraction(self.conn, jid, resolved_src, [
            P("issue", "resolved", "All sorted now", item="leak"),
        ])
        self.conn.commit()
        facts = db.list_facts(self.conn, jid)
        leak_open = next(f for f in facts if f.field == "issue" and f.item == "leak" and f.state == "unresolved" and f.active)
        rattling = next(f for f in facts if f.field == "issue" and "rattl" in (f.item or "") and f.active)
        leak_resolved = next(f for f in facts if f.field == "issue" and f.state == "resolved" and f.active)
        if leak_resolved.review_status not in ("needs_review", "conflicting"):
            db.update_fact(self.conn, leak_resolved.id, review_status="needs_review")
            self.conn.commit()
        st = pipeline.build_state(self.conn, jid)
        presented = ask.enrich_items([
            AskItem(text="Leak reported fixed.", kind="from_record", fact_ids=[leak_resolved.id]),
        ], st)
        self.assertEqual(presented[0].related_fact_ids, [leak_open.id])
        self.assertNotIn(rattling.id, presented[0].related_fact_ids)

    def test_stale_guard(self):
        self.assertTrue(ask.is_stale(1, 2, 1, 1))
        self.assertTrue(ask.is_stale(1, 1, 1, 2))
        self.assertFalse(ask.is_stale(4, 4, 3, 3))

    def test_non_job_replies_need_no_citations(self):
        jid = self._job("Ask greeting", "Unit A-1", [P("asset_id", "observed", "Unit A-1", value="A-1")])
        st = pipeline.build_state(self.conn, jid)
        ask.validate_items([AskItem(text="Hi. I can help with this job’s notes.", kind="message")], st, "greeting")
        ask.validate_items([AskItem(text="I didn’t understand that. Could you rephrase your question?", kind="message")], st, "clarification")
        ask.validate_items([AskItem(text="Preventive maintenance is scheduled upkeep.", kind="message")], st, "general")
        stripped = ask.normalize_items([
            AskItem(text="Hi.", kind="from_record", fact_ids=[st.facts[0].id], requirement_ids=["R1"]),
        ], "greeting")
        self.assertEqual(stripped[0].kind, "message")
        self.assertEqual(stripped[0].fact_ids, [])
        self.assertEqual(stripped[0].requirement_ids, [])
        enriched = ask.enrich_items([
            AskItem(text="Hi.", kind="from_record", fact_ids=[st.facts[0].id]),
        ], st, "greeting")
        self.assertEqual(enriched[0].related_fact_ids, [])
        self.assertEqual(enriched[0].fact_ids, [])

    def test_job_message_items_are_not_given_related_facts(self):
        jid = self._job("Ask message item", "There is a leak.", [P("issue", "unresolved", "There is a leak", item="leak")])
        st = pipeline.build_state(self.conn, jid)
        presented = ask.enrich_items([
            AskItem(text="The record is not enough to specify a repair.", kind="message", fact_ids=[st.facts[0].id]),
        ], st, "job")
        self.assertEqual(presented[0].kind, "message")
        self.assertEqual(presented[0].fact_ids, [])
        self.assertEqual(presented[0].related_fact_ids, [])

    def test_greeting_kind_not_used_for_unintelligible_input(self):
        hi_kind, hi_items = ask.correct_non_job_kind(
            "Hi", "greeting", [AskItem(text="Hello!", kind="message")]
        )
        self.assertEqual(hi_kind, "greeting")
        self.assertEqual(hi_items[0].text, "Hello!")
        help_kind, _ = ask.correct_non_job_kind(
            "What can you help me with?", "greeting", [AskItem(text="I can help with notes.", kind="message")]
        )
        self.assertEqual(help_kind, "greeting")
        unclear_kind, unclear_items = ask.correct_non_job_kind(
            "xqzplm", "greeting", [AskItem(text="Hello!", kind="message")]
        )
        self.assertEqual(unclear_kind, "clarification")
        self.assertIn("rephrase", unclear_items[0].text.lower())
        self.assertEqual(unclear_items[0].kind, "message")
        job_kind, job_items = ask.correct_non_job_kind(
            "FP-017", "job", [AskItem(text="Equipment ID is FP-017.", kind="from_record", fact_ids=[1])]
        )
        self.assertEqual(job_kind, "job")
        self.assertEqual(job_items[0].fact_ids, [1])

    def test_repair_boundary_replaces_job_how_to(self):
        self.assertTrue(ask.is_repair_how_to("How do I fix this leak?"))
        self.assertTrue(ask.is_repair_how_to("How can I diagnose the noise?"))
        self.assertFalse(ask.is_repair_how_to("What is preventive maintenance?"))
        self.assertFalse(ask.is_repair_how_to("Is the leak resolved?"))
        kind, items = ask.apply_repair_boundary(
            "How do I fix this leak?",
            "job",
            [AskItem(text="That’s all sorted now.", kind="from_record", fact_ids=[1])],
        )
        self.assertEqual(kind, "job")
        self.assertEqual(items[0].kind, "message")
        self.assertEqual(items[0].fact_ids, [])
        self.assertIn("verified repair procedure", items[0].text)
        self.assertNotIn("sorted", items[0].text)
        general_kind, general_items = ask.apply_repair_boundary(
            "How do I perform preventive maintenance in general?",
            "general",
            [AskItem(text="It is scheduled upkeep.", kind="message")],
        )
        self.assertEqual(general_kind, "general")
        self.assertEqual(general_items[0].text, "It is scheduled upkeep.")

    def test_history_is_bounded_and_clipped(self):
        hist = [{"role": "user", "text": f"q{i}"} for i in range(20)]
        clipped = ask.clip_history(hist)
        self.assertEqual(len(clipped), 8)
        self.assertEqual(clipped[0]["text"], "q12")
        self.assertEqual(clipped[-1]["text"], "q19")
        long = ask.clip_history([{"role": "assistant", "text": "x" * 800}])
        self.assertEqual(len(long[0]["text"]), ask.MAX_HISTORY_CHARS)
        self.assertTrue(long[0]["text"].endswith("…"))

    def test_history_is_in_prompt_and_not_treated_as_evidence(self):
        jid = self._job("Ask follow-up")
        captured: list = []
        payload = _items([{
            "kind": "missing_information",
            "text": "Equipment ID: not recorded.",
            "source_ids": [],
            "fact_ids": [],
            "requirement_ids": ["R1"],
        }])

        def fake(messages, _schema):
            captured.append(messages)
            return llm.ChatResult(content=payload, metrics={"wall_ms": 9})

        with patch("app.ask.llm.chat", side_effect=fake):
            resp = ask.answer_question(self.conn, jid, "What about the test?", [
                {"role": "user", "text": "What’s still open?"},
                {"role": "assistant", "text": "The leak is still open."},
            ])
        self.assertEqual(resp.kind, "job")
        user = captured[0][1]["content"]
        self.assertIn("What’s still open?", user)
        self.assertIn("The leak is still open.", user)
        self.assertIn("not evidence", user)
        self.assertIn("What about the test?", user)
        self.assertIn("CURRENT MESSAGE:", user)
        self.assertNotIn("The leak is still open.", resp.items[0].text)

    def test_photo_caption_is_labeled_not_analyzed(self):
        jid = db.create_job(self.conn, "Ask photo")
        db.insert_source(self.conn, jid, "photo", "Filter housing after swap", photo_path="a" * 32 + ".png")
        self.conn.commit()
        text, _ = ask.context_from_conn(self.conn, jid)
        self.assertIn("caption only", text)
        self.assertIn("not analyzed", text)
        self.assertNotIn("a" * 32, text)


class AskApiTest(unittest.TestCase):
    def setUp(self):
        from app import main

        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "t.db"

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
        self.tmp.cleanup()

    def _seed(self, title, text, proposals):
        jid = self.client.post("/api/jobs", json={"title": title}).json()["job"]["id"]
        conn = db.connect(self.db_path)
        src = db.insert_source(conn, jid, "typed", text)
        state.apply_extraction(conn, jid, src, proposals)
        conn.commit()
        conn.close()
        return jid

    def _snapshot(self, jid):
        st = self.client.get(f"/api/jobs/{jid}").json()
        return {
            "job": st["job"],
            "facts": [(f["id"], f["field"], f["state"], f["review_status"], f["value"], f["active"]) for f in st["facts"]],
            "sources": [(s["id"], s["text"]) for s in st["sources"]],
            "handoff": st["job"]["handoff_note"],
            "checklist": [(r["id"], r["status"]) for r in st["checklist"]],
        }

    def test_ask_does_not_mutate_job(self):
        jid = self._seed(
            "Ask persist",
            "There is a leak. Replaced three filters.",
            [
                P("issue", "unresolved", "There is a leak", item="leak"),
                P("part_replaced", "reported_complete", "Replaced three filters", item="filters", value="3"),
            ],
        )
        before = self._snapshot(jid)
        fact_id = before["facts"][0][0]
        source_id = before["sources"][0][0]
        payload = _items([{
            "kind": "from_record",
            "text": "A leak is still open.",
            "source_ids": [source_id],
            "fact_ids": [fact_id],
            "requirement_ids": ["R4"],
        }])
        with patch("app.ask.llm.chat", side_effect=_chat(payload)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={"question": "What’s still unfinished?"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["job_id"], jid)
        self.assertEqual(resp.json()["kind"], "job")
        self.assertEqual(self._snapshot(jid), before)

    def test_greeting_strips_model_citations(self):
        jid = self._seed(
            "Ask greet cite",
            "Unit A-1. There is a leak.",
            [
                P("asset_id", "observed", "Unit A-1", value="A-1"),
                P("issue", "unresolved", "There is a leak", item="leak"),
            ],
        )
        before = self._snapshot(jid)
        fact_id = before["facts"][0][0]
        source_id = before["sources"][0][0]
        payload = _items([{
            "kind": "from_record",
            "text": "Hi. I can help with this job’s notes and open work.",
            "source_ids": [source_id],
            "fact_ids": [fact_id],
            "requirement_ids": ["R1"],
        }], kind="greeting")
        with patch("app.ask.llm.chat", side_effect=_chat(payload)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={"question": "Hi"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["kind"], "greeting")
        self.assertEqual(body["items"][0]["kind"], "message")
        self.assertEqual(body["items"][0]["fact_ids"], [])
        self.assertEqual(body["items"][0]["source_ids"], [])
        self.assertEqual(body["items"][0]["requirement_ids"], [])
        self.assertEqual(body["items"][0]["related_fact_ids"], [])
        self.assertEqual(self._snapshot(jid), before)

    def test_clarification_has_no_checklist_fallback(self):
        jid = self.client.post("/api/jobs", json={"title": "Ask unclear"}).json()["job"]["id"]
        before = self._snapshot(jid)
        payload = _items([{
            "kind": "message",
            "text": "I didn’t understand that. Could you rephrase your question?",
            "source_ids": [],
            "fact_ids": [],
            "requirement_ids": [],
        }], kind="clarification")
        with patch("app.ask.llm.chat", side_effect=_chat(payload)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={"question": "asda"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["kind"], "clarification")
        self.assertEqual(body["items"][0]["requirement_ids"], [])
        self.assertNotIn("Equipment ID", body["items"][0]["text"])
        self.assertEqual(self._snapshot(jid), before)

    def test_history_does_not_mutate_job(self):
        jid = self._seed(
            "Ask hist persist",
            "There is a leak.",
            [P("issue", "unresolved", "There is a leak", item="leak")],
        )
        before = self._snapshot(jid)
        payload = _items([{
            "kind": "from_record",
            "text": "The leak is still open.",
            "source_ids": [before["sources"][0][0]],
            "fact_ids": [before["facts"][0][0]],
            "requirement_ids": ["R4"],
        }])
        with patch("app.ask.llm.chat", side_effect=_chat(payload)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={
                "question": "What about the leak?",
                "history": [
                    {"role": "user", "text": "What’s still unfinished?"},
                    {"role": "assistant", "text": "A leak is still open."},
                ],
            })
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self._snapshot(jid), before)

    def test_missing_information_mixed_cites_fail_after_retry(self):
        jid = self._seed(
            "Ask mixed missing",
            "I haven't run the final test yet.",
            [P("final_test", "explicitly_not_complete", "I haven't run the final test yet")],
        )
        st = self.client.get(f"/api/jobs/{jid}").json()
        fact_id = st["facts"][0]["id"]
        source_id = st["sources"][0]["id"]
        before = self._snapshot(jid)
        bad = _items([{
            "kind": "missing_information",
            "text": "Asset ID is not recorded.",
            "source_ids": [source_id],
            "fact_ids": [fact_id],
            "requirement_ids": ["R1"],
        }])
        with patch("app.ask.llm.chat", side_effect=_chat(bad)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={"question": "What’s still unfinished?"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(self._snapshot(jid), before)

    def test_invalid_citations_fail_after_retry(self):
        jid = self.client.post("/api/jobs", json={"title": "Ask bad cite"}).json()["job"]["id"]
        bad = _items([{"text": "done", "source_ids": [404], "fact_ids": [], "requirement_ids": []}])
        with patch("app.ask.llm.chat", side_effect=_chat(bad)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={"question": "What is left?"})
        self.assertEqual(resp.status_code, 422)
        after = self.client.get(f"/api/jobs/{jid}").json()
        self.assertEqual(after["facts"], [])
        self.assertEqual(after["sources"], [])

    def test_empty_job_can_cite_checklist(self):
        jid = self.client.post("/api/jobs", json={"title": "Ask empty api"}).json()["job"]["id"]
        payload = _items([{
            "kind": "missing_information",
            "text": "No work has been recorded on this job yet.",
            "source_ids": [],
            "fact_ids": [],
            "requirement_ids": ["R1", "R2", "R3", "R4"],
        }])
        with patch("app.ask.llm.chat", side_effect=_chat(payload)):
            resp = self.client.post(f"/api/jobs/{jid}/ask", json={"question": "What’s still unfinished?"})
        self.assertEqual(resp.status_code, 200, resp.text)
        text = resp.json()["items"][0]["text"]
        self.assertIn("Equipment ID: not recorded.", text)
        self.assertIn("Work done and parts used: not recorded.", text)
        self.assertNotIn("Asset ID confirmed", text)

    def test_answer_echoes_job_id_for_stale_guard(self):
        a = self.client.post("/api/jobs", json={"title": "Ask stale A"}).json()["job"]["id"]
        b = self.client.post("/api/jobs", json={"title": "Ask stale B"}).json()["job"]["id"]
        payload = _items([{
            "kind": "missing_information",
            "text": "Nothing recorded.",
            "source_ids": [],
            "fact_ids": [],
            "requirement_ids": ["R1"],
        }])
        with patch("app.ask.llm.chat", side_effect=_chat(payload)):
            resp = self.client.post(f"/api/jobs/{a}/ask", json={"question": "Status?"})
        self.assertEqual(resp.json()["job_id"], a)
        self.assertNotEqual(resp.json()["job_id"], b)
        self.assertTrue(ask.is_stale(b, resp.json()["job_id"], 1, 1))


if __name__ == "__main__":
    unittest.main()
