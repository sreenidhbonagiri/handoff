"""Run FieldPilot and the one-pass baseline on labeled cases with the same local model.

Usage (from repo root, with Ollama running):
  .venv/bin/python evals/run_eval.py                       # dev cases
  .venv/bin/python evals/run_eval.py --cases evals/fresh/cases.json
  .venv/bin/python evals/run_eval.py --skip-baseline
"""

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import db, llm, pipeline  # noqa: E402
from app.config import MODEL  # noqa: E402
from app.schemas import ObservationIn  # noqa: E402
from app.state import normalize_value  # noqa: E402
import baseline  # noqa: E402


def _stems(text: str | None) -> set[str]:
    # Four-letter stems so plurals match ("bolt" vs "bolts").
    return {w[:4] for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) >= 3}


def _candidates(facts: list[dict[str, Any]], exp: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in facts:
        if f["field"] != exp["field"]:
            continue
        if exp.get("item") and not _stems(exp["item"]) <= _stems(f"{f.get('item') or ''} {f.get('quote') or ''}"):
            continue
        out.append(f)
    return out


def _matches(f: dict[str, Any], exp: dict[str, Any]) -> bool:
    if "value" in exp and normalize_value(f.get("value")) != normalize_value(exp["value"]):
        return False
    if "state" in exp and f["state"] != exp["state"]:
        return False
    if "review_status" in exp and f.get("review_status") != exp["review_status"]:
        return False
    return True


def score_facts(facts: list[dict[str, Any]], expect: dict[str, Any]) -> dict[str, Any]:
    exp_facts = expect.get("facts", [])
    correct = state_ok = found = false_completion = 0
    failures = []
    for exp in exp_facts:
        cands = _candidates(facts, exp)
        if cands:
            found += 1
            if "state" in exp and any(c["state"] == exp["state"] for c in cands):
                state_ok += 1
            if exp.get("state") in ("planned", "explicitly_not_complete") and any(
                c["state"] == "reported_complete" for c in cands
            ):
                false_completion += 1
        if any(_matches(c, exp) for c in cands):
            correct += 1
        else:
            failures.append({"expected": exp, "got": cands})
    absent_violations = []
    for pattern in expect.get("absent", []):
        hits = [c for c in _candidates(facts, pattern) if _matches(c, pattern)]
        if hits:
            absent_violations.append({"pattern": pattern, "got": hits})
            if pattern.get("state") == "reported_complete":
                false_completion += 1
    unexpected = [f for f in facts if not any(_candidates([f], e) for e in exp_facts)]
    return {
        "expected": len(exp_facts),
        "correct": correct,
        "found": found,
        "state_labeled": sum(1 for e in exp_facts if "state" in e),
        "state_ok": state_ok,
        "false_completion": false_completion,
        "absent_violations": absent_violations,
        "unexpected": unexpected,
        "failures": failures,
    }


def run_fieldpilot(case: dict[str, Any], conn) -> dict[str, Any]:
    job_id = db.create_job(conn, case["id"])
    latencies: list[float] = []
    last_source = None
    st = pipeline.build_state(conn, job_id)
    try:
        for turn in case["turns"]:
            if "edit_last" in turn:
                st = pipeline.edit_source(conn, last_source, turn["edit_last"])
            else:
                obs = ObservationIn(
                    text=turn["text"], kind=turn.get("kind", "typed"), answers_requirement=turn.get("answers_requirement")
                )
                st = pipeline.add_observation(conn, job_id, obs)
            last_source = st.sources[-1].id
            if st.last_run and st.last_run.wall_ms:
                latencies.append(st.last_run.wall_ms)
    except llm.LLMError as e:
        return {"error": str(e)}
    facts = [f.model_dump() for f in st.facts if f.active]
    expect = case["expect"]
    result = score_facts(facts, expect)
    checklist = {r.id: r.status for r in st.checklist}
    result["checklist_expected"] = expect.get("checklist", {})
    result["checklist_got"] = {k: checklist.get(k) for k in expect.get("checklist", {})}
    result["checklist_ok"] = sum(1 for k, v in expect.get("checklist", {}).items() if checklist.get(k) == v)
    if "next_question" in expect:
        got = st.next_question.requirement_id if st.next_question else None
        result["next_question_ok"] = got == expect["next_question"]
        result["next_question"] = st.next_question.text if st.next_question else None
    result["ready_ok"] = "ready" not in expect or st.readiness.ready == expect["ready"]
    result["latency_ms"] = latencies
    result["facts"] = facts
    return result


def _notes_for_baseline(case: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for turn in case["turns"]:
        if "edit_last" in turn:
            notes[-1] = turn["edit_last"]
        else:
            notes.append(turn["text"])
    return notes


def run_baseline(case: dict[str, Any]) -> dict[str, Any]:
    report, facts, metrics, error = baseline.run(_notes_for_baseline(case))
    if error:
        return {"error": error}
    result = score_facts(facts, case["expect"])
    expect = case["expect"]
    result["ready_ok"] = "ready" not in expect or report.ready_for_closeout == expect["ready"]
    result["latency_ms"] = [metrics.get("wall_ms", 0)]
    result["report"] = report.model_dump()
    return result


def summarize(name: str, results: dict[str, dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    ok = {k: v for k, v in results.items() if "error" not in v}
    tot = lambda key: sum(r[key] for r in ok.values())  # noqa: E731
    correction_cases = [c["id"] for c in cases if "correction" in c.get("tags", []) and c["id"] in ok]
    lat = [x for r in ok.values() for x in r["latency_ms"]]
    summary = {
        "system": name,
        "cases_run": len(ok),
        "cases_errored": len(results) - len(ok),
        "fact_correctness": f"{tot('correct')}/{tot('expected')}",
        "omitted_expected_facts": tot("expected") - tot("found"),
        "task_state_correctness": f"{tot('state_ok')}/{tot('state_labeled')}",
        "false_completions": tot("false_completion"),
        "forbidden_facts_present": sum(len(r["absent_violations"]) for r in ok.values()),
        "correction_handling": f"{sum(1 for c in correction_cases if ok[c]['correct'] == ok[c]['expected'] and not ok[c]['absent_violations'])}/{len(correction_cases)}",
        "unexpected_facts_for_manual_review": sum(len(r["unexpected"]) for r in ok.values()),
        "ready_flag_correct": f"{sum(1 for r in ok.values() if r['ready_ok'])}/{len(ok)}",
        "median_latency_ms": round(statistics.median(lat)) if lat else None,
    }
    if name == "fieldpilot":
        labeled = sum(len(r["checklist_expected"]) for r in ok.values())
        summary["checklist_status_correct"] = f"{tot('checklist_ok')}/{labeled}"
        nq = [r["next_question_ok"] for r in ok.values() if "next_question_ok" in r]
        summary["follow_up_targets_expected_item"] = f"{sum(nq)}/{len(nq)}"
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(ROOT / "evals" / "dev" / "cases.json"))
    ap.add_argument("--skip-baseline", action="store_true")
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text())
    runnable = [c for c in cases if not c.get("skip")]
    skipped = [(c["id"], c["skip"]) for c in cases if c.get("skip")]
    info = llm.model_info()
    print(f"model={MODEL} quant={info['quantization']} device={info['device']}")
    if not info["model_installed"]:
        sys.exit(f"Cannot run: {info['error']}")

    fp_results: dict[str, Any] = {}
    bl_results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "eval.db")
        for case in runnable:
            print(f"[fieldpilot] {case['id']} {case['title']}")
            fp_results[case["id"]] = run_fieldpilot(case, conn)
            if not args.skip_baseline:
                print(f"[baseline]   {case['id']}")
                bl_results[case["id"]] = run_baseline(case)
        conn.close()

    summaries = [summarize("fieldpilot", fp_results, runnable)]
    if bl_results:
        summaries.append(summarize("baseline", bl_results, runnable))

    print("\nSkipped:", ", ".join(f"{cid} ({why})" for cid, why in skipped) or "none")
    for s in summaries:
        print(f"\n== {s['system']}")
        for k, v in s.items():
            if k != "system":
                print(f"  {k:38} {v}")
    print("\nFailures (fieldpilot):")
    for cid, r in fp_results.items():
        if "error" in r:
            print(f"  {cid}: ERROR {r['error']}")
            continue
        for f in r["failures"]:
            print(f"  {cid}: expected {f['expected']} got {[(g['item'], g['value'], g['state'], g['review_status']) for g in f['got']]}")
        for v in r["absent_violations"]:
            print(f"  {cid}: forbidden fact present {v['pattern']}")

    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{Path(args.cases).parent.name}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"model": MODEL, "info": info, "skipped": skipped, "summaries": summaries,
                               "fieldpilot": fp_results, "baseline": bl_results}, indent=2, default=str))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
