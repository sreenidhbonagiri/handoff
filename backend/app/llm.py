"""Local Ollama client. No remote fallback: if Ollama is unavailable, callers get LLMError."""

import json
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import KEEP_ALIVE, LLM_TIMEOUT_S, MODEL, NUM_CTX, OLLAMA_URL
from .schemas import model_output_schema

# Calls are serialized so concurrent requests never load a second context on a 16 GB machine.
_lock = threading.Lock()


class LLMError(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class Extraction:
    items: list[Any]
    raw: str
    metrics: dict[str, Any]


SYSTEM_PROMPT = """You extract job-record facts from a maintenance technician's note.
Return JSON matching the schema. List proposals in the order the statements appear in the note.

Fields:
- asset_id: the unit/asset identifier stated. value = the ID exactly as written. item = null. state = observed.
- part_replaced: a part replaced, installed or swapped. item = part name. value = quantity as digits if stated ("the belt" or "a belt" is 1), else null.
- test: any test, check or trial run of the equipment ("ran the final test", "tested it", "will test it", "haven't tested it").
  item = the test's name only if the note names it ("final test", "pressure test"); null if the note just says "test it" or "tested it".
  value = "passed", "failed", or null when no result is stated. Use test only when the note's words mention testing, checking or running.
  Testing that is planned ("will test it", "test it tomorrow") or not done ("haven't tested it") is still test, with state planned or explicitly_not_complete. It is never follow_up or issue.
- issue: a problem, symptom or defect with any equipment (noise, leak, vibration, error code, broken machine...). item = short description of the problem, using the note's words.
  state = unresolved if it is still present or not said to be fixed; resolved only if the note explicitly says this problem is fixed, stopped or gone.
  Saying something needs fixing or will be fixed means the problem remains: unresolved.
  If the note explicitly says there are no remaining problems, use item = "no remaining issues", state = resolved.
- follow_up: a follow-up visit, ticket or work order for something unfinished (not a test; tests are always test). item = what it is for.
- other_action: any other maintenance action (cleaned, tightened, inspected, lubricated...). item = the action.

States:
- reported_complete: the note says it was done (past tense: "replaced", "tested", "finished X").
- planned: the note says it will be done later or is intended ("need to", "will", "going to", "tomorrow", "continue later").
- explicitly_not_complete: the note says it has not been done, could not be done, or was skipped ("haven't", "didn't", "not yet", "couldn't").
  "I haven't done X yet" is explicitly_not_complete, not planned, unless the note also says when or that it will be done.
- unresolved / resolved: only for issue.
- observed: only for asset_id.

Rules:
- quote: copy the exact contiguous words from the note that support the proposal. Do not paraphrase.
  The quote must contain the words that show the state and name the item ("replaced the belt", not "I just finished it").
  Do not include a different remark or claim in the same quote, even if joined by "and" or a comma.
  Keep the negation or correction words the claim depends on ("haven't tested it", "sorry, two belts").
- Never add work, parts, results or problems that the note does not state.
- Intent or remaining work ("need to fix", "will repair", "continue tomorrow") is never reported_complete and never resolves an issue.
- test value = "passed" or "failed" only when the note states that result. Keep a test and its result in one proposal
  whose quote covers both ("Ran the final test and it passed").
- A passing test does not resolve a problem. Only mark a problem resolved when the note says that problem is fixed or gone.
- One sentence can hold several claims: "fixed X and the noise stopped" is an action on X plus an issue (noise) resolved.
  Seeing that a problem stopped is part of that issue, not a test.
- Self-correction inside the note ("two, actually three", "sorry, I mean"): output TWO proposals. First the original value
  with a quote of only the original words, then the corrected value with a quote of only the corrected words and
  corrects = the exact words being corrected. The corrected proposal's value is the new value, never the old one.
- If the note updates an existing fact listed below, set target_fact_id to that fact's id.
  Set corrects only when the speaker explicitly says the earlier statement was wrong.
- If the note states a different value for an existing fact without saying it is a correction, do not set corrects.
- Ignore remarks that are not about equipment or the work (traffic, weather, personal comments).
  A problem with other equipment is still an issue unless the job context says it is outside this job. If nothing is relevant, return an empty proposals list.
- Use null for anything unknown.
- Give each statement its own proposal with its own quote. Never output a proposal with an empty quote; omit fields the note does not mention.
- A repair of a part ("repaired the hose", "fixed the valve") is other_action with item = the repair.

Example of a self-correction. Note: "Pump P-2. Swapped one seal, no wait, two seals."
{"proposals": [
 {"quote": "Pump P-2", "field": "asset_id", "item": null, "value": "P-2", "state": "observed", "corrects": null, "target_fact_id": null},
 {"quote": "Swapped one seal", "field": "part_replaced", "item": "seal", "value": "1", "state": "reported_complete", "corrects": null, "target_fact_id": null},
 {"quote": "two seals", "field": "part_replaced", "item": "seal", "value": "2", "state": "reported_complete", "corrects": "one seal", "target_fact_id": null}
]}

Example of one sentence with an action and a resolution. Note: "Swapped the fan belt and the squeal stopped."
{"proposals": [
 {"quote": "Swapped the fan belt", "field": "part_replaced", "state": "reported_complete", "item": "fan belt", "value": "1", "corrects": null, "target_fact_id": null},
 {"quote": "the squeal stopped", "field": "issue", "state": "resolved", "item": "squeal", "value": null, "corrects": null, "target_fact_id": null}
]}"""


def chat(messages: list[dict[str, str]], schema: dict[str, Any]) -> ChatResult:
    body = {
        "model": MODEL,
        "messages": messages,
        "format": schema,
        "think": False,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }
    with _lock:
        start = time.perf_counter()
        try:
            resp = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=LLM_TIMEOUT_S)
        except httpx.HTTPError as e:
            raise LLMError(f"Local Ollama is not reachable at {OLLAMA_URL}: {e}") from e
        wall_ms = (time.perf_counter() - start) * 1000
    if resp.status_code != 200:
        raise LLMError(f"Ollama returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    metrics = {
        "wall_ms": round(wall_ms, 1),
        "total_ms": data.get("total_duration", 0) / 1e6,
        "load_ms": data.get("load_duration", 0) / 1e6,
        "prompt_tokens": data.get("prompt_eval_count"),
        "eval_tokens": data.get("eval_count"),
        "eval_ms": data.get("eval_duration", 0) / 1e6,
    }
    return ChatResult(content=data.get("message", {}).get("content", ""), metrics=metrics)


def _facts_context(active_facts: list[dict[str, Any]]) -> str:
    if not active_facts:
        return "none"
    keys = ("id", "field", "item", "value", "state", "quote")
    lines = []
    for f in active_facts:
        d = {k: f[k] for k in keys}
        if d["field"] == "final_test":
            d.update(field="test", item="final functional test")
        lines.append(json.dumps(d))
    return "\n".join(lines)


def extract(
    text: str, active_facts: list[dict[str, Any]], question: str | None = None, job_context: str | None = None,
) -> Extraction:
    parts = []
    if job_context:
        parts.append(f"Job context:\n{job_context}")
    parts.append(f"Existing active facts (one JSON object per line):\n{_facts_context(active_facts)}")
    if question:
        parts.append(f"The technician is answering this question: {question}")
    parts.append(f'Technician note:\n"""\n{text}\n"""')
    result = chat(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}],
        model_output_schema(),
    )
    try:
        data = json.loads(result.content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Model output was not valid JSON: {result.content[:300]}") from e
    items = data.get("proposals") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LLMError(f"Model output had no proposals list: {result.content[:300]}")
    return Extraction(items=items, raw=result.content, metrics=result.metrics)


def model_info() -> dict[str, Any]:
    """Reachability and quantization details for the disclosure panel."""
    info: dict[str, Any] = {
        "ollama_reachable": False,
        "model_installed": False,
        "quantization": None,
        "parameter_size": None,
        "device": f"{platform.machine()} {platform.platform(terse=True)}",
        "error": None,
    }
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
        info["ollama_reachable"] = True
        names = {m.get("name") for m in tags.get("models", [])}
        info["model_installed"] = MODEL in names or f"{MODEL}:latest" in names
        if info["model_installed"]:
            details = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": MODEL}, timeout=5).json().get("details", {})
            info["quantization"] = details.get("quantization_level")
            info["parameter_size"] = details.get("parameter_size")
        else:
            info["error"] = f"Model {MODEL} is not installed. Run: ollama pull {MODEL}"
    except httpx.HTTPError as e:
        info["error"] = f"Ollama not reachable at {OLLAMA_URL}: {e}"
    return info
