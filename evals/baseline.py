"""One-pass baseline: the same local model writes the closeout record in a single call.

It receives the same notes and the same checklist. It is a sensible prompt, not a weakened one.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel

from app import llm
from app.checklist import load_checklist

Status = Literal["completed", "planned", "not_completed"]


class BPart(BaseModel):
    part: str
    quantity: str | None
    status: Status


class BAction(BaseModel):
    action: str
    status: Status


class BTest(BaseModel):
    status: Literal["completed", "planned", "not_completed", "not_recorded"]
    result: Literal["passed", "failed"] | None


class BIssue(BaseModel):
    description: str
    status: Literal["unresolved", "resolved"]


class BReport(BaseModel):
    asset_id: str | None
    parts_replaced: list[BPart]
    other_actions: list[BAction]
    final_test: BTest
    issues: list[BIssue]
    follow_up: str | None
    missing_information: list[str]
    ready_for_closeout: bool


def _prompt() -> str:
    labels = "\n".join(f"- {r['label']}" for r in load_checklist()["requirements"])
    return f"""You write a maintenance job closeout record from a technician's notes.
Report only what the notes state; do not invent work, parts or results.
Distinguish completed, planned, and not completed work. A plan is not a completion.
Apply explicit corrections the technician makes. If two notes disagree without a correction, mention it in missing_information.
Report every problem and whether it remains; a passing test does not fix a separate problem.
Ignore statements unrelated to the job.
The closeout checklist is:
{labels}
List any checklist information that is missing in missing_information.
Set ready_for_closeout to true only if every checklist item is recorded."""


_STATE = {"completed": "reported_complete", "planned": "planned", "not_completed": "explicitly_not_complete"}


def run(notes: list[str]) -> tuple[BReport | None, list[dict[str, Any]], dict[str, Any], str | None]:
    """Returns (report, facts in the evaluator's shape, metrics, error)."""
    numbered = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes))
    try:
        result = llm.chat(
            [{"role": "system", "content": _prompt()}, {"role": "user", "content": f"Technician notes in order:\n{numbered}"}],
            BReport.model_json_schema(),
        )
        report = BReport.model_validate_json(result.content)
    except (llm.LLMError, ValueError) as e:
        return None, [], {}, str(e)

    facts: list[dict[str, Any]] = []
    if report.asset_id:
        facts.append({"field": "asset_id", "item": None, "value": report.asset_id, "state": "observed"})
    for p in report.parts_replaced:
        facts.append({"field": "part_replaced", "item": p.part, "value": p.quantity, "state": _STATE[p.status]})
    for a in report.other_actions:
        facts.append({"field": "other_action", "item": a.action, "value": None, "state": _STATE[a.status]})
    if report.final_test.status != "not_recorded":
        facts.append({"field": "final_test", "item": None, "value": report.final_test.result, "state": _STATE[report.final_test.status]})
    for issue in report.issues:
        facts.append({"field": "issue", "item": issue.description, "value": None, "state": issue.status})
    if report.follow_up:
        facts.append({"field": "follow_up", "item": report.follow_up, "value": None, "state": "planned"})
    for f in facts:
        f.setdefault("review_status", "accepted")
        f.setdefault("quote", "")
    return report, facts, result.metrics, None


if __name__ == "__main__":
    import sys

    print(json.dumps(run(sys.argv[1:])[1], indent=2))
