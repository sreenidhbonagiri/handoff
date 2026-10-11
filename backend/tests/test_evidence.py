"""Status-evidence rules and job scoping. Proposals are hand-written stand-ins for model output,
including wrong ones, so the deterministic checks are exercised without the model."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import checklist, db, evidence, pipeline, state  # noqa: E402
from app.schemas import ALLOWED_STATES  # noqa: E402
from test_state import P  # noqa: E402


def check(field, state_, quote, item=None, value=None, correction=False, answer=False):
    return evidence.assess(field, state_, value, item, quote, ALLOWED_STATES[field],
                           is_correction=correction, is_answer=answer)


class AssessTest(unittest.TestCase):
    def test_intent_never_resolves_an_issue(self):
        for quote in ["I need to fix the pipe", "I will repair the pipe", "Going to patch the pipe leak tomorrow",
                      "the leak is still there", "I haven't fixed the leak", "Have to continue on the pipe tomorrow"]:
            a = check("issue", "resolved", quote, item="pipe leak")
            self.assertEqual(a.state, "unresolved", quote)
            self.assertIsNone(a.review, quote)

    def test_explicit_resolution_naming_the_issue_is_accepted(self):
        for quote, item in [("verified the leak has stopped", "leak"), ("The rattle is gone", "rattle"),
                            ("no remaining issues", "no remaining issues"), ("vibration no longer present", "vibration"),
                            ("the pipe isn't leaking anymore", "pipe leak")]:
            a = check("issue", "resolved", quote, item=item)
            self.assertEqual((a.state, a.review), ("resolved", None), quote)

    def test_ambiguous_resolution_requires_review(self):
        cases = [("I just finished it", "pipe leak"),           # no resolution wording
                 ("All fixed", "leak"),                        # does not name the issue
                 ("fixed the leak but it still drips", "leak")]  # mixed
        for quote, item in cases:
            a = check("issue", "resolved", quote, item=item)
            self.assertEqual(a.state, "resolved", quote)
            self.assertIsNotNone(a.review, quote)

    def test_intent_is_not_completion(self):
        for quote in ["I need to replace the belt", "I'll replace the belt tomorrow", "will swap the belt",
                      "need to continue the belt job tomorrow"]:
            self.assertEqual(check("part_replaced", "reported_complete", quote, item="belt").state, "planned", quote)

    def test_non_completion_is_distinct_from_plan(self):
        for quote in ["I haven't tested it", "I haven't done the final test yet", "didn't run the final test",
                      "final test not done"]:
            self.assertEqual(check("final_test", "planned", quote).state, "explicitly_not_complete", quote)
            self.assertEqual(check("final_test", "reported_complete", quote).state, "explicitly_not_complete", quote)
        for quote in ["I'll test it tomorrow", "final test later", "going to run the test next visit"]:
            self.assertEqual(check("final_test", "explicitly_not_complete", quote).state, "planned", quote)
            self.assertEqual(check("final_test", "planned", quote).state, "planned", quote)
        # Both a non-completion and a plan: either label is supported, keep the model's.
        both = "I haven't tested it, I'll do it tomorrow"
        self.assertEqual(check("final_test", "planned", both).state, "planned")
        self.assertEqual(check("final_test", "explicitly_not_complete", both).state, "explicitly_not_complete")

    def test_completion_must_name_what_was_done(self):
        self.assertIsNotNone(check("part_replaced", "reported_complete", "I just finished it", item="pipe").review)
        self.assertIsNone(check("part_replaced", "reported_complete", "replaced five pipes", item="pipe").review)
        self.assertIsNone(check("part_replaced", "reported_complete", "actually five", item="pipe", correction=True).review)
        self.assertIsNone(check("other_action", "reported_complete", "Yes, done", item="lubrication", answer=True).review)

    def test_test_result_must_be_stated(self):
        self.assertIsNotNone(check("final_test", "reported_complete", "I fixed the test", value="passed").review)
        self.assertIsNone(check("final_test", "reported_complete", "The final test passed", value="passed").review)
        self.assertIsNotNone(check("final_test", "reported_complete", "The final test passed", value="failed").review)
        self.assertIsNone(check("final_test", "reported_complete", "final test failed", value="failed").review)
        self.assertIsNone(check("final_test", "reported_complete", "ran the final test", value=None).review)

    def test_completion_needs_a_performed_action(self):
        self.assertIsNotNone(check("other_action", "reported_complete", "Traffic was terrible", item="traffic was terrible").review)
        for quote, item in [("Lubricated the fan motor bearings", "lubricated bearings"), ("Ran the pressure test", "pressure test"),
                            ("Swapped the contactor", "contactor"), ("The flow test passed", "flow test")]:
            self.assertIsNone(check("other_action", "reported_complete", quote, item=item).review, quote)

    def test_request_is_not_completion(self):
        for quote in ["Go ahead and mark this job complete", "please mark it done", "close out this job"]:
            self.assertIsNotNone(check("other_action", "reported_complete", quote, item="mark this job complete").reject, quote)
        self.assertIsNone(check("other_action", "reported_complete", "Marked the cable", item="marked the cable").reject)

    def test_test_claim_must_mention_a_test(self):
        for quote in ["Go ahead and mark this job complete", "verified the leak has stopped", "all done"]:
            self.assertIsNotNone(check("final_test", "reported_complete", quote, value="passed").reject, quote)
        self.assertIsNone(check("final_test", "reported_complete", "Yes, it passed", value="passed", answer=True).reject)
        self.assertIsNone(check("final_test", "explicitly_not_complete", "I haven't tested it").reject)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")
        self.job = db.create_job(self.conn, "test")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, text, proposals, job=None, kind="typed"):
        job = job or self.job
        src = db.insert_source(self.conn, job, kind, text)
        rejected = state.apply_extraction(self.conn, job, src, proposals)
        self.conn.commit()
        return src, rejected

    def active(self, job=None):
        return [f for f in db.list_facts(self.conn, job or self.job) if f.active]

    def statuses(self):
        return {s.id: s.status for s in checklist.evaluate(self.active())[0]}

    def test_wrong_model_output_from_remaining_work_note(self):
        # Mirrors a stored bad output: resolution and completion claimed from remaining-work wording.
        text = "I need to fix the pipe. I just finished it. I need to continue tomorrow."
        self.add(text, [
            P("issue", "resolved", "I need to fix the pipe", item="pipe leak"),
            P("part_replaced", "reported_complete", "I just finished it", item="pipe", value="4"),
            P("follow_up", "planned", "I need to continue tomorrow", item="fix pipe"),
        ])
        facts = {f.field: f for f in self.active()}
        self.assertEqual(facts["issue"].state, "unresolved")
        self.assertIn("re-labelled unresolved", facts["issue"].note)
        self.assertEqual(facts["part_replaced"].review_status, "needs_review")
        st = self.statuses()
        self.assertEqual(st["R2"], "conflicting")  # unclear completion does not count as work done
        self.assertEqual(st["R4"], "unresolved")
        self.assertFalse(checklist.evaluate(self.active())[2].ready)

    def test_unclear_resolution_does_not_supersede_open_issue(self):
        self.add("The leak is still there.", [P("issue", "unresolved", "The leak is still there", item="leak")])
        self.add("All sorted now.", [P("issue", "resolved", "All sorted now", item="leak")])
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual(sorted((f.state, f.review_status) for f in issues),
                         [("resolved", "needs_review"), ("unresolved", "accepted")])
        st, question, _ = checklist.evaluate(self.active())
        self.assertEqual({s.id: s.status for s in st}["R4"], "conflicting")
        self.assertIn("unclear", question.text)

        held = next(f for f in issues if f.review_status == "needs_review")
        state.confirm_fact(self.conn, self.job, held.id)
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual([(f.state, f.review_status) for f in issues], [("resolved", "confirmed")])

    def test_confirming_unnamed_resolution_updates_the_only_open_issue(self):
        self.add("There is a slow leak at the drain valve.", [
            P("issue", "unresolved", "There is a slow leak at the drain valve", item="slow leak at the drain valve")])
        leak = self.active()[0]
        self.add("That's all sorted now.", [P("issue", "resolved", "That's all sorted now", item="no remaining issues")])
        held = next(f for f in self.active() if f.review_status == "needs_review")
        self.assertEqual(held.supersedes, leak.id)
        self.assertIsNone(next(f for f in db.list_facts(self.conn, self.job) if f.id == leak.id).superseded_by)

        state.confirm_fact(self.conn, self.job, held.id)
        facts = {f.id: f for f in db.list_facts(self.conn, self.job)}
        self.assertEqual(facts[leak.id].superseded_by, held.id)
        self.assertEqual([(f.state, f.review_status) for f in self.active() if f.field == "issue"], [("resolved", "confirmed")])
        self.assertEqual(self.statuses()["R4"], "reported")

    def test_unnamed_resolution_with_several_open_issues_asks_which(self):
        self.add("Leak at the valve. Fan is rattling.", [
            P("issue", "unresolved", "Leak at the valve", item="leak"), P("issue", "unresolved", "Fan is rattling", item="rattling")])
        self.add("All sorted now.", [P("issue", "resolved", "All sorted now", item="no remaining issues")])
        held = next(f for f in self.active() if f.review_status == "needs_review")
        self.assertIsNone(held.supersedes)
        self.assertIn("say which one is resolved", held.note)

    def test_explicit_resolution_supersedes_open_issue(self):
        self.add("The leak is still there.", [P("issue", "unresolved", "The leak is still there", item="leak")])
        self.add("I repaired the pipe and verified the leak has stopped.", [
            P("part_replaced", "reported_complete", "I repaired the pipe", item="pipe"),
            P("issue", "resolved", "verified the leak has stopped", item="leak"),
        ])
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual([(f.state, f.review_status) for f in issues], [("resolved", "accepted")])

    def test_not_done_test_is_not_planned(self):
        self.add("I haven't done the final test yet.", [P("final_test", "planned", "I haven't done the final test yet")])
        self.assertEqual(self.active()[0].state, "explicitly_not_complete")
        self.assertEqual(self.statuses()["R3"], "not_complete")

    def test_correction_repeating_old_value_takes_new_value_from_quote(self):
        self.add("Replaced two filters\u2014actually three.", [P(
            "part_replaced", "reported_complete", "Replaced two filters\u2014actually three",
            item="filters", value="2", corrects="two filters")])
        f = self.active()[0]
        self.assertEqual((f.value, f.corrected_from, f.review_status), ("3", "two filters", "accepted"))
        self.assertIn("value 3 taken from", f.note)
        history = [h for h in db.list_facts(self.conn, self.job) if h.superseded_by == f.id]
        self.assertEqual([(h.value, h.quote) for h in history], [("2", "two filters")])

    def test_broad_quote_is_tightened_to_the_supporting_clause(self):
        text = "Traffic was terrible this morning and the coffee machine in the lobby is broken."
        self.add(text, [P("issue", "unresolved", text[:-1], item="coffee machine in the lobby is broken")])
        f = self.active()[0]
        self.assertEqual(f.quote, "the coffee machine in the lobby is broken")
        self.assertNotIn("Traffic", f.quote)
        self.assertEqual(text[f.quote_start:f.quote_end], f.quote)

    def test_tightening_keeps_negation_and_a_test_result(self):
        self.add("I haven't tested it since the valve swap.", [
            P("final_test", "explicitly_not_complete", "I haven't tested it since the valve swap")])
        self.assertEqual(self.active()[0].quote, "I haven't tested it since the valve swap")
        self.add("Ran the final test and it passed.", [
            P("final_test", "reported_complete", "Ran the final test and it passed", value="passed")])
        tests = [f for f in self.active() if f.field == "final_test"]
        self.assertEqual(tests[0].quote, "Ran the final test and it passed")

    def test_confirm_legacy_held_resolution_recovers_the_only_open_issue(self):
        self.add("There is a slow leak at the drain valve.", [
            P("issue", "unresolved", "There is a slow leak at the drain valve", item="slow leak at the drain valve")])
        leak = self.active()[0]
        src = db.insert_source(self.conn, self.job, "typed", "That's all sorted now.")
        held_id = db.insert_fact(
            self.conn, job_id=self.job, source_id=src.id, field="issue", item="no remaining issues",
            item_key=state.item_key("issue", "no remaining issues"), value=None, state="resolved",
            quote="That's all sorted now.", quote_start=0, quote_end=20, review_status="needs_review",
        )
        self.conn.commit()
        held = next(f for f in self.active() if f.id == held_id)
        self.assertIsNone(held.supersedes)
        state.confirm_fact(self.conn, self.job, held_id)
        facts = {f.id: f for f in db.list_facts(self.conn, self.job)}
        self.assertEqual(facts[leak.id].superseded_by, held_id)
        self.assertEqual(facts[held_id].supersedes, leak.id)
        self.assertEqual([(f.state, f.review_status) for f in self.active() if f.field == "issue"],
                         [("resolved", "confirmed")])

    def test_confirm_legacy_held_resolution_errors_when_target_is_ambiguous(self):
        self.add("Leak at the valve. Fan is rattling.", [
            P("issue", "unresolved", "Leak at the valve", item="leak"),
            P("issue", "unresolved", "Fan is rattling", item="rattling"),
        ])
        src = db.insert_source(self.conn, self.job, "typed", "That's all sorted now.")
        held_id = db.insert_fact(
            self.conn, job_id=self.job, source_id=src.id, field="issue", item="no remaining issues",
            item_key=state.item_key("issue", "no remaining issues"), value=None, state="resolved",
            quote="That's all sorted now.", quote_start=0, quote_end=20, review_status="needs_review",
        )
        self.conn.commit()
        with self.assertRaises(ValueError) as ctx:
            state.confirm_fact(self.conn, self.job, held_id)
        self.assertIn("does not say which existing fact it replaces", str(ctx.exception))
        issues = [f for f in self.active() if f.field == "issue"]
        self.assertEqual(sorted((f.state, f.review_status) for f in issues),
                         [("resolved", "needs_review"), ("unresolved", "accepted"), ("unresolved", "accepted")])

    def test_correction_repeating_old_value_without_new_number_is_held(self):
        self.add("Replaced two filters, I think.", [P(
            "part_replaced", "reported_complete", "Replaced two filters", item="filters", value="2", corrects="two filters")])
        self.assertEqual(self.active()[0].review_status, "needs_review")

    def test_unstated_test_result_needs_review(self):
        self.add("Okay, I fixed the test.", [P("final_test", "reported_complete", "I fixed the test", value="passed")])
        self.assertEqual(self.active()[0].review_status, "needs_review")
        self.assertEqual(self.statuses()["R3"], "conflicting")


class TestMappingTest(unittest.TestCase):
    """Model `test` proposals are mapped to a record using the job's checklist and facts."""

    setUp, tearDown, add, active, statuses = (
        ApplyTest.setUp, ApplyTest.tearDown, ApplyTest.add, ApplyTest.active, ApplyTest.statuses,
    )

    def test_unnamed_test_maps_to_the_only_test(self):
        self.add("I haven't tested it.", [P("test", "explicitly_not_complete", "I haven't tested it", item="test")])
        f = self.active()[0]
        self.assertEqual((f.field, f.state, f.review_status), ("final_test", "explicitly_not_complete", "accepted"))
        self.assertEqual(self.statuses()["R3"], "not_complete")

    def test_planned_unnamed_test_updates_checklist(self):
        self.add("I'll test it tomorrow.", [P("test", "planned", "I'll test it tomorrow", item=None)])
        self.assertEqual(self.statuses()["R3"], "planned")

    def test_unnamed_test_with_several_tests_asks(self):
        self.add("Ran the pressure test and it passed.", [
            P("test", "reported_complete", "Ran the pressure test", item="pressure test", value="passed")])
        self.assertEqual([(f.field, f.item) for f in self.active()], [("other_action", "pressure test")])
        self.add("I haven't tested it since.", [P("test", "explicitly_not_complete", "I haven't tested it", item="test it")])
        held = [f for f in self.active() if f.review_status == "needs_review"]
        self.assertEqual([(f.field, f.state) for f in held], [("final_test", "explicitly_not_complete")])
        self.assertIn("the final functional test or the pressure test", held[0].note)
        st, question, _ = checklist.evaluate(self.active())
        self.assertEqual({s.id: s.status for s in st}["R3"], "conflicting")
        self.assertIn("Which test does this refer to", question.text)

    def test_unnamed_test_filed_as_other_action_is_mapped(self):
        self.add("The flow test passed.", [P("test", "reported_complete", "The flow test passed", item="flow test", value="passed")])
        self.add("Still need to test it once more.", [
            P("other_action", "planned", "Still need to test it once more", item="test it once more")])
        held = [f for f in self.active() if f.review_status == "needs_review"]
        self.assertEqual([(f.field, f.state) for f in held], [("final_test", "planned")])
        self.assertIn("the flow test", held[0].note)

    def test_named_tests_map_directly(self):
        self.add("Pressure test passed.", [P("test", "reported_complete", "Pressure test passed", item="pressure test", value="passed")])
        self.add("Final test is planned for later.", [P("test", "planned", "Final test is planned for later", item="final test")])
        facts = {(f.field, f.state, f.review_status) for f in self.active()}
        self.assertIn(("final_test", "planned", "accepted"), facts)
        self.assertIn(("other_action", "reported_complete", "accepted"), facts)

    def test_split_final_test_result_is_rejoined(self):
        self.add("Ran the final test and it passed.", [
            P("test", "reported_complete", "Ran the final test"),
            P("test", "reported_complete", "and it passed", value="passed"),
        ])
        tests = [f for f in self.active() if f.field == "final_test"]
        self.assertEqual([(f.value, f.state, f.review_status) for f in tests],
                         [("passed", "reported_complete", "accepted")])
        self.assertIn("final test", tests[0].quote.lower())
        self.assertIn("passed", tests[0].quote.lower())

    def test_split_named_test_result_uses_nearby_sentence(self):
        self.add("Performed the pressure test. It failed.", [
            P("test", "reported_complete", "Performed the pressure test", item="pressure test"),
            P("test", "reported_complete", "It failed", value="failed"),
        ])
        tests = [f for f in self.active() if f.field == "other_action"]
        self.assertEqual([(f.item, f.value, f.review_status) for f in tests],
                         [("pressure test", "failed", "accepted")])
        self.assertIn("pressure test", tests[0].quote.lower())
        self.assertIn("failed", tests[0].quote.lower())

    def test_result_with_several_nearby_tests_is_held(self):
        self.add("Ran the pressure test and the flow test. It passed.", [
            P("test", "reported_complete", "Ran the pressure test", item="pressure test"),
            P("test", "reported_complete", "the flow test", item="flow test"),
            P("test", "reported_complete", "It passed", value="passed"),
        ])
        held = [f for f in self.active() if f.review_status == "needs_review"]
        self.assertTrue(held)
        self.assertTrue(any("which test" in (f.note or "") for f in held))
        self.assertFalse(any(
            f.value == "passed" and f.review_status == "accepted" for f in self.active()
        ))

    def test_all_clear_does_not_resolve_an_open_named_issue(self):
        self.add("There is a leak at the valve.", [
            P("issue", "unresolved", "There is a leak at the valve", item="leak")])
        leak = next(f for f in self.active() if f.field == "issue")
        self.add("No other issues on the unit.", [
            P("issue", "resolved", "No other issues on the unit", item="no remaining issues")])
        facts = {f.id: f for f in db.list_facts(self.conn, self.job)}
        self.assertIsNone(facts[leak.id].superseded_by)
        self.assertEqual((facts[leak.id].state, facts[leak.id].review_status), ("unresolved", "accepted"))
        held = [f for f in self.active() if f.review_status == "needs_review"]
        self.assertEqual([f.item for f in held], ["no remaining issues"])
        self.assertEqual(self.statuses()["R4"], "conflicting")

    def test_test_claim_without_test_words_is_rejected(self):
        _, rejected = self.add("I repaired the pipe and verified the leak has stopped.", [
            P("other_action", "reported_complete", "I repaired the pipe", item="repaired the pipe"),
            P("issue", "resolved", "verified the leak has stopped", item="leak"),
            P("test", "reported_complete", "verified the leak has stopped", value="passed"),
        ])
        self.assertEqual([r.reason for r in rejected], ["quote does not mention a test"])
        self.assertEqual(sorted((f.field, f.state) for f in self.active()),
                         [("issue", "resolved"), ("other_action", "reported_complete")])
        self.assertEqual(self.statuses()["R3"], "not_recorded")


class JobScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_new_job_is_empty_and_isolated(self):
        old = db.create_job(self.conn, "old")
        src = db.insert_source(self.conn, old, "typed", "Unit FP-1. Replaced two belts.")
        state.apply_extraction(self.conn, old, src, [P("asset_id", "observed", "Unit FP-1", value="FP-1")])
        self.conn.commit()

        new = db.create_job(self.conn, "new")
        st = pipeline.build_state(self.conn, new)
        self.assertEqual((st.job.id, st.sources, st.facts, st.rejected, st.last_run), (new, [], [], [], None))
        self.assertTrue(all(s.status == "not_recorded" or s.status == "not_applicable" for s in st.checklist))
        self.assertEqual(len(pipeline.build_state(self.conn, old).facts), 1)

        old_fact = db.list_facts(self.conn, old)[0].id
        with self.assertRaises(ValueError):
            state.confirm_fact(self.conn, new, old_fact)
        with self.assertRaises(ValueError):
            state.review_fact(self.conn, new, old_fact, "x", "observed")


if __name__ == "__main__":
    unittest.main()
