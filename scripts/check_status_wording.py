"""Real local-inference check of fact types and status wording.

Each case runs in its own new job through the running backend (qwen3:4b via Ollama); earlier
turns set up job context. The resulting active facts are checked against rules, not exact outputs.
Run with the backend up:  .venv/bin/python scripts/check_status_wording.py
"""

import sys

import httpx

API = "http://127.0.0.1:8000/api"
COUNTED = ("accepted", "confirmed")
COMPLETION = {"reported_complete", "resolved"}
WORK = {"part_replaced", "other_action"}

# need: (fields, state) that must exist among counted facts
# held: (fields, state) that must exist among facts held for review
# forbid: (fields, states) that must not exist among counted facts
CASES = [
    {"turns": ["The leak is still there. I need to repair the pipe tomorrow."],
     "need": [({"issue"}, "unresolved")], "forbid": [(None, COMPLETION)]},
    {"turns": ["I haven't tested it."],
     "need": [({"final_test"}, "explicitly_not_complete")], "forbid": [(None, COMPLETION), ({"issue"}, None)]},
    {"turns": ["Haven't had a chance to test it yet."],
     "need": [({"final_test"}, "explicitly_not_complete")], "forbid": [(None, COMPLETION), ({"issue"}, None)]},
    {"turns": ["I'll test it tomorrow."],
     "need": [({"final_test"}, "planned")], "forbid": [(None, COMPLETION)]},
    {"turns": ["Unit RT-4. Swapped the contactor.", "Going to test it first thing in the morning."],
     "need": [({"final_test"}, "planned"), (WORK, "reported_complete")], "forbid": [({"final_test"}, COMPLETION)]},
    {"turns": ["I repaired the pipe and verified the leak has stopped."],
     "need": [(WORK, "reported_complete"), ({"issue"}, "resolved")], "forbid": [({"final_test"}, None)]},
    {"turns": ["Patched the hose and the drip is gone now."],
     "need": [(WORK, "reported_complete"), ({"issue"}, "resolved")], "forbid": [({"final_test"}, None)]},
    {"turns": ["Unit HX-3. Ran the pressure test on the loop and it passed.", "I haven't tested it since the valve swap."],
     "need": [({"other_action"}, "reported_complete")], "held": [({"final_test"}, "explicitly_not_complete")],
     "forbid": [({"final_test"}, None)]},
    {"turns": ["Unit CW-2. The flow test passed.", "Still need to test it once more before I leave."],
     "need": [({"other_action"}, "reported_complete")], "held": [({"final_test"}, "planned")],
     "forbid": [({"final_test"}, None)]},
    {"turns": ["Unit HX-5. The leak check is scheduled for Friday.", "Will test it after lunch."],
     "held": [({"final_test"}, "planned")], "forbid": [({"final_test"}, None), (None, COMPLETION)]},
    {"turns": ["Unit EF-8. Traffic was terrible and the coffee machine in the lobby is broken. Lubricated the fan motor bearings."],
     "need": [({"issue"}, "unresolved"), (WORK, "reported_complete")], "forbid": [({"final_test"}, None)],
     "forbid_quotes": ["Traffic"]},
]


def _has(facts, fields, state):
    return any((fields is None or f["field"] in fields) and (state is None or f["state"] == state) for f in facts)


def _hits(facts, fields, states):
    return [f for f in facts if (fields is None or f["field"] in fields) and (states is None or f["state"] in states)]


def main() -> int:
    failures = 0
    with httpx.Client(timeout=180) as client:
        for case in CASES:
            job = client.post(f"{API}/jobs", json={"title": "fact type check"}).json()
            assert not job["sources"] and not job["facts"], "new job was not empty"
            jid = job["job"]["id"]
            ms = []
            for turn in case["turns"]:
                r = client.post(f"{API}/jobs/{jid}/observations", json={"text": turn, "kind": "typed"})
                r.raise_for_status()
                st = r.json()
                ms.append(st["last_run"]["wall_ms"])
            active = [f for f in st["facts"] if f["active"]]
            counted = [f for f in active if f["review_status"] in COUNTED]
            held = [f for f in active if f["review_status"] == "needs_review"]
            problems = []
            for fields, want in case.get("need", []):
                if not _has(counted, fields, want):
                    problems.append(f"missing counted {sorted(fields)}={want}")
            for fields, want in case.get("held", []):
                if not _has(held, fields, want):
                    problems.append(f"missing held {sorted(fields)}={want}")
            for fields, states in case.get("forbid", []):
                bad = _hits(counted, fields, states)
                if bad:
                    problems.append(f"forbidden counted {[(f['field'], f['state'], f['quote']) for f in bad]}")
            for word in case.get("forbid_quotes", []):
                bad = [f for f in counted if word.lower() in f["quote"].lower()]
                if bad:
                    problems.append(f"counted fact from unrelated remark: {[(f['field'], f['quote']) for f in bad]}")
            failures += bool(problems)
            print(f"{'FAIL' if problems else 'ok  '} job {jid} ({' + '.join(f'{m:.0f}' for m in ms)} ms): {' / '.join(case['turns'])}")
            for f in active:
                tag = "" if f["review_status"] == "accepted" else f" [{f['review_status']}]"
                print(f"       {f['field']}({f['item']}) value={f['value']} {f['state']}{tag} \u2190 \u201c{f['quote']}\u201d"
                      + (f"  note: {f['note']}" if f["note"] else ""))
            for rj in st["rejected"]:
                print(f"       rejected: {rj['proposal'].get('field')} {rj['proposal'].get('state')} \u2014 {rj['reason']}")
            if st["next_question"]:
                print(f"       next question: {st['next_question']['text']}")
            for p in problems:
                print(f"       !! {p}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
