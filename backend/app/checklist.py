"""Evaluate the supplied checklist against active facts and pick one follow-up question.

Missing evidence is reported as not recorded; it never implies the work was not performed.
"""

import json
from functools import lru_cache
from typing import Any

from .config import CHECKLIST_PATH
from .schemas import Fact, Question, Readiness, RequirementStatus

DISCLAIMER = (
    "This report reflects recorded documentation only and does not certify equipment safety. "
    "Quotations show what was said; they do not independently verify the work."
)


@lru_cache
def load_checklist() -> dict[str, Any]:
    return json.loads(CHECKLIST_PATH.read_text())


def _q(fact: Fact) -> str:
    return f"\u201c{fact.quote}\u201d"


def _unsettled(f: Fact) -> bool:
    """Cannot count yet: one side of a conflict, or wording that needs a person to confirm it."""
    return f.review_status in ("conflicting", "needs_review")


def _conflicting(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if _unsettled(f)]


def _status(status: str, satisfied: bool, detail: str, facts: list[Fact]) -> dict[str, Any]:
    return {"status": status, "satisfied": satisfied, "detail": detail, "fact_ids": [f.id for f in facts]}


def _asset_id(facts: list[Fact]) -> dict[str, Any]:
    ids = [f for f in facts if f.field == "asset_id"]
    if not ids:
        return _status("not_recorded", False, "No asset ID recorded.", [])
    if _conflicting(ids):
        return _status("conflicting", False, "Asset IDs disagree: " + " vs ".join(f.value or "?" for f in ids), ids)
    return _status("reported", True, f"Reported asset: {ids[-1].value}", ids)


def _completed_work(facts: list[Fact]) -> dict[str, Any]:
    work = [f for f in facts if f.field in ("part_replaced", "other_action")]
    if not work:
        return _status("not_recorded", False, "No completed action recorded.", [])
    if _conflicting(work):
        return _status("conflicting", False, "Conflicting statements about the work performed.", _conflicting(work))
    done = [f for f in work if f.state == "reported_complete"]
    parts_missing_qty = [f for f in done if f.field == "part_replaced" and not f.value]
    if parts_missing_qty:
        names = ", ".join(f.item or "part" for f in parts_missing_qty)
        return _status("not_recorded", False, f"Quantity not recorded for: {names}.", parts_missing_qty)
    if done:
        return _status("reported", True, f"{len(done)} completed action(s) reported.", done)
    if any(f.state == "planned" for f in work):
        return _status("planned", False, "Work is planned but not reported complete.", work)
    return _status("not_complete", False, "Work reported as not completed.", work)


def _final_test(facts: list[Fact]) -> dict[str, Any]:
    tests = [f for f in facts if f.field == "final_test"]
    if not tests:
        return _status("not_recorded", False, "No final functional test recorded.", [])
    if _conflicting(tests):
        return _status("conflicting", False, "Conflicting statements about the final test.", tests)
    t = tests[-1]
    if t.state == "planned":
        return _status("planned", False, "Final test planned for later; no result recorded.", tests)
    if t.state == "explicitly_not_complete":
        return _status("not_complete", False, "Final test stated as not done.", tests)
    if not t.value:
        return _status("not_recorded", False, "Final test reported done, but its result is not recorded.", tests)
    return _status("reported", True, f"Final test result: {t.value}.", tests)


def _issues(facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if f.field == "issue"]


def _issue_status(facts: list[Fact]) -> dict[str, Any]:
    issues = _issues(facts)
    if not issues:
        return _status("not_recorded", False, "No statement about remaining issues.", [])
    if _conflicting(issues):
        return _status("conflicting", False, "An issue's status needs confirmation.", _conflicting(issues))
    open_issues = [f for f in issues if f.state == "unresolved"]
    if open_issues:
        names = ", ".join(f.item or "issue" for f in open_issues)
        return _status("unresolved", True, f"Unresolved: {names}.", open_issues)
    return _status("reported", True, "All reported issues recorded as resolved.", issues)


def _follow_up_if_issue(facts: list[Fact]) -> dict[str, Any]:
    open_issues = [f for f in _issues(facts) if f.state == "unresolved" or _unsettled(f)]
    if not open_issues:
        return _status("not_applicable", True, "No unresolved issue recorded.", [])
    follow = [f for f in facts if f.field == "follow_up" and not _unsettled(f)]
    if follow:
        return _status("reported", True, f"Follow-up recorded: {follow[-1].item or follow[-1].quote}.", follow)
    return _status("not_recorded", False, "An issue remains but no follow-up is recorded.", open_issues)


RULES = {
    "asset_id": _asset_id,
    "completed_work": _completed_work,
    "final_test": _final_test,
    "issue_status": _issue_status,
    "follow_up_if_issue": _follow_up_if_issue,
}

_NOT_RECORDED_QUESTIONS = {
    "asset_id": "What asset ID is printed on the unit's label?",
    "completed_work": "What work was completed, and which parts and quantities were used?",
    "final_test": "Was the final functional test performed, and did it pass or fail?",
    "issue_status": "Are any problems still present on the unit, or were all of them resolved?",
    "follow_up_if_issue": "What follow-up is planned for the unresolved issue?",
}


def _question(req: dict[str, Any], st: RequirementStatus, by_id: dict[int, Fact]) -> Question:
    cited = [by_id[i] for i in st.fact_ids if i in by_id]
    prefix = f"Procedure \u00a7{req['section']} ({req['label']}): "
    held = [f for f in cited if f.review_status == "needs_review"]
    if st.status == "conflicting" and held and len(held) == len([f for f in cited if f.review_status != "accepted"]):
        asks = [part for part in (held[0].note or "").split("; ") if part.endswith("?")]
        if asks:
            text = f"{_q(held[0])} \u2014 {asks[0][0].upper()}{asks[0][1:]}"
        else:
            text = f"This statement is unclear: {_q(held[0])}. What exactly was done, and is it finished?"
    elif st.status == "conflicting":
        quotes = " vs ".join(_q(f) for f in cited) or "earlier statements"
        text = f"These statements disagree: {quotes}. Which is correct?"
    elif st.status == "planned" and cited:
        text = f"This was recorded as planned ({_q(cited[-1])}). Has it been done, and what was the result?"
    elif st.status == "not_complete" and cited:
        text = f"This was recorded as not completed ({_q(cited[-1])}). Has it been completed since?"
    elif req["rule"] == "follow_up_if_issue" and cited:
        text = f"An issue remains unresolved ({_q(cited[0])}). What follow-up is planned?"
    elif req["rule"] == "completed_work" and cited:
        names = ", ".join(f.item or "part" for f in cited)
        text = f"How many were replaced ({names})?"
    elif req["rule"] == "final_test" and cited:
        text = f"The final test was mentioned ({_q(cited[-1])}). Did it pass or fail?"
    else:
        text = _NOT_RECORDED_QUESTIONS[req["rule"]]
    return Question(requirement_id=req["id"], text=prefix + text, fact_ids=st.fact_ids)


def evaluate(active: list[Fact]) -> tuple[list[RequirementStatus], Question | None, Readiness]:
    reqs = load_checklist()["requirements"]
    statuses = [
        RequirementStatus(id=r["id"], section=r["section"], label=r["label"], **RULES[r["rule"]](active))
        for r in reqs
    ]
    by_id = {f.id: f for f in active}
    pairs = list(zip(reqs, statuses))

    question = None
    conflicted = [(r, s) for r, s in pairs if s.status == "conflicting"]
    unmet = [(r, s) for r, s in pairs if not s.satisfied]
    if conflicted:
        question = _question(*conflicted[0], by_id)
    elif unmet:
        question = _question(*unmet[0], by_id)

    ready = not unmet
    open_issue = any(s.status == "unresolved" for s in statuses)
    if ready and open_issue:
        summary = "Documentation complete; an unresolved issue remains with a recorded follow-up."
    elif ready:
        summary = "Documentation complete for the supplied checklist."
    else:
        summary = f"Not ready: {len(unmet)} checklist item(s) missing, planned, or needing confirmation."
    return statuses, question, Readiness(ready=ready, summary=summary, disclaimer=DISCLAIMER)
