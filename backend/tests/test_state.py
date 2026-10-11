"""Validator and checklist tests. Proposals here are hand-written inputs to the deterministic code;
the model is not involved. Run: .venv/bin/python -m unittest discover backend/tests"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import checklist, db, pipeline, state  # noqa: E402


def P(field, state_, quote, item=None, value=None, corrects=None, target=None):
    return {"field": field, "item": item, "value": value, "state": state_, "quote": quote,
            "corrects": corrects, "target_fact_id": target}


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")
        self.job = db.create_job(self.conn, "test")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, text, proposals):
        src = db.insert_source(self.conn, self.job, "typed", text)
        rejected = state.apply_extraction(self.conn, self.job, src, proposals)
        self.conn.commit()
        return src, rejected

    def active(self):
        return [f for f in db.list_facts(self.conn, self.job) if f.active]

    def evaluate(self):
        return checklist.evaluate(self.active())

    def test_merged_correction_keeps_original_in_history(self):
        text = "Unit FP-017. Replaced two filters\u2014actually three."
        self.add(text, [P(
            "part_replaced", "reported_complete", "Replaced two filters\u2014actually three",
            item="filters", value="2", corrects="two filters",
        )])
        parts = [f for f in db.list_facts(self.conn, self.job) if f.field == "part_replaced"]
        active = [f for f in parts if f.active]
        self.assertEqual(len(active), 1)
        self.assertEqual((active[0].value, active[0].corrected_from), ("3", "two filters"))
        history = [f for f in parts if f.superseded_by == active[0].id]
        self.assertEqual([(h.value, h.quote, h.superseded_by) for h in history],
                         [("2", "two filters", active[0].id)])
        self.assertEqual(active[0].supersedes, history[0].id)

    def test_correction_does_not_invent_unsupported_history(self):
        self.add("Replaced three filters.", [P(
            "part_replaced", "reported_complete", "Replaced three filters",
            item="filters", value="3", corrects="two filters",
        )])
        facts = [f for f in db.list_facts(self.conn, self.job) if f.field == "part_replaced"]
        self.assertEqual([(f.value, f.active, f.corrected_from) for f in facts], [("3", True, None)])

    def test_self_correction_supersedes_and_keeps_history(self):
        text = "Unit FP-017. Replaced two filters\u2014actually three. The rattling is still there. I'll do the final test later."
        _, rejected = self.add(text, [
            P("asset_id", "observed", "Unit FP-017", value="FP-017"),
            P("part_replaced", "reported_complete", "Replaced two filters", item="filters", value="2"),
            P("part_replaced", "reported_complete", "actually three", item="filter", value="3", corrects="two filters"),
            P("issue", "unresolved", "The rattling is still there", item="rattling"),
            P("final_test", "planned", "I'll do the final test later"),
        ])
        self.assertEqual(rejected, [])
        parts = [f for f in self.active() if f.field == "part_replaced"]
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].value, "3")
        self.assertEqual(parts[0].corrected_from, "two filters")
        history = [f for f in db.list_facts(self.conn, self.job) if f.superseded_by == parts[0].id]
        self.assertEqual([h.value for h in history], ["2"])

        statuses, question, readiness = self.evaluate()
        by_id = {s.id: s.status for s in statuses}
        self.assertEqual(by_id["R3"], "planned")
        self.assertEqual(by_id["R4"], "unresolved")
        self.assertEqual(question.requirement_id, "R3")
        self.assertFalse(readiness.ready)
        self.assertIn("does not certify equipment safety", readiness.disclaimer)

    def test_quote_must_be_substring(self):
        _, rejected = self.add("Replaced the belt.", [P("part_replaced", "reported_complete", "Replaced two belts", item="belt")])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(self.active(), [])

    def test_disallowed_state_rejected(self):
        _, rejected = self.add("Unit X-1.", [P("asset_id", "reported_complete", "Unit X-1", value="X-1")])
        self.assertIn("not allowed", rejected[0].reason)

    def test_different_value_without_correction_conflicts(self):
        self.add("Replaced two capacitors.", [P("part_replaced", "reported_complete", "Replaced two capacitors", item="capacitor", value="2")])
        self.add("Replaced three capacitors.", [P("part_replaced", "reported_complete", "Replaced three capacitors", item="capacitors", value="3")])
        parts = self.active()
        self.assertEqual(len(parts), 2)
        self.assertTrue(all(f.review_status == "conflicting" for f in parts))
        statuses, question, _ = self.evaluate()
        self.assertEqual({s.id: s.status for s in statuses}["R2"], "conflicting")
        self.assertEqual(question.requirement_id, "R2")

        state.confirm_fact(self.conn, self.job, parts[1].id)
        remaining = self.active()
        self.assertEqual([f.value for f in remaining], ["3"])
        self.assertEqual(remaining[0].review_status, "confirmed")

    def test_planned_test_becomes_complete_only_with_new_evidence(self):
        self.add("I'll run the test later.", [P("final_test", "planned", "I'll run the test later")])
        self.add("Test passed.", [P("final_test", "reported_complete", "Test passed", value="passed")])
        tests = self.active()
        self.assertEqual(len(tests), 1)
        self.assertEqual((tests[0].state, tests[0].value), ("reported_complete", "passed"))

    def test_passed_test_does_not_resolve_issue(self):
        self.add("Still a rattling noise.", [P("issue", "unresolved", "Still a rattling noise", item="rattling noise")])
        self.add("Final test passed.", [P("final_test", "reported_complete", "Final test passed", value="passed")])
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual(issues[0].state, "unresolved")
        statuses, _, _ = self.evaluate()
        by_id = {s.id: s.status for s in statuses}
        self.assertEqual(by_id["R3"], "reported")
        self.assertEqual(by_id["R4"], "unresolved")
        self.assertEqual(by_id["R5"], "not_recorded")

    def test_resolution_must_name_the_issue(self):
        src, _ = self.add("Still a rattling noise.", [P("issue", "unresolved", "Still a rattling noise", item="rattling noise")])
        issue_id = self.active()[0].id
        self.add("Final test passed, all good.", [P("issue", "resolved", "all good", item="rattling noise", target=issue_id)])
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual(sorted((f.state, f.review_status) for f in issues),
                         [("resolved", "needs_review"), ("unresolved", "accepted")])
        self.assertEqual({s.id: s.status for s in self.evaluate()[0]}["R4"], "conflicting")

        self.add("The rattle is gone now.", [P("issue", "resolved", "The rattle is gone now", item="rattling noise", target=issue_id)])
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual([(f.state, f.review_status) for f in issues], [("resolved", "accepted")])

    def test_missing_evidence_is_not_recorded(self):
        statuses, question, readiness = self.evaluate()
        self.assertEqual({s.status for s in statuses if s.id != "R5"}, {"not_recorded"})
        self.assertEqual(question.requirement_id, "R1")
        self.assertFalse(readiness.ready)

    def test_ready_with_unresolved_issue_and_follow_up(self):
        self.add(
            "Unit A-1. Replaced 2 belts. Final test passed. Squeal remains. Opened ticket for the squeal.",
            [
                P("asset_id", "observed", "Unit A-1", value="A-1"),
                P("part_replaced", "reported_complete", "Replaced 2 belts", item="belt", value="2"),
                P("final_test", "reported_complete", "Final test passed", value="passed"),
                P("issue", "unresolved", "Squeal remains", item="squeal"),
                P("follow_up", "reported_complete", "Opened ticket for the squeal", item="ticket for squeal"),
            ],
        )
        _, question, readiness = self.evaluate()
        self.assertIsNone(question)
        self.assertTrue(readiness.ready)
        self.assertIn("unresolved issue remains", readiness.summary)

    def test_source_edit_invalidates_and_restores(self):
        src, _ = self.add("Replaced five fuses.", [P("part_replaced", "reported_complete", "Replaced five fuses", item="fuse", value="5")])
        state.invalidate_source(self.conn, self.job, src.id)
        self.assertEqual(self.active(), [])

    def test_report_renders(self):
        self.add("Unit B-2. Replaced one valve.", [
            P("asset_id", "observed", "Unit B-2", value="B-2"),
            P("part_replaced", "reported_complete", "Replaced one valve", item="valve", value="one"),
        ])
        from app import report

        st = pipeline.build_state(self.conn, self.job)
        html = report.render_html(st)
        self.assertIn("does not certify equipment safety", html)
        self.assertIn("Replaced one valve", html)
        self.assertEqual(report.build_json(st)["asset"][0]["value"], "B-2")


if __name__ == "__main__":
    unittest.main()
