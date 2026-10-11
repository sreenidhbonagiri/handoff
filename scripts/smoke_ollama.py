"""Smoke test: qwen3:4b through Ollama with thinking disabled and a JSON-schema format.

Uses only the standard library so it runs before the backend venv exists.
Usage: python3 scripts/smoke_ollama.py [model]
"""

import json
import platform
import sys
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen3:4b"

SCHEMA = {
    "type": "object",
    "properties": {
        "asset_id": {"type": ["string", "null"]},
        "quantity": {"type": ["integer", "null"]},
        "quote": {"type": "string"},
    },
    "required": ["asset_id", "quantity", "quote"],
}


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        OLLAMA + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def main() -> None:
    show = post("/api/show", {"model": MODEL})
    details = show.get("details", {})
    print(f"model={MODEL} params={details.get('parameter_size')} quant={details.get('quantization_level')}")
    print(f"device={platform.machine()} {platform.platform()}")

    note = "Pump P-4. Swapped one seal, no wait, two seals."
    for attempt in ("cold", "warm"):
        start = time.perf_counter()
        out = post(
            "/api/chat",
            {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "Extract the asset ID and final corrected quantity. quote = exact words."},
                    {"role": "user", "content": note},
                ],
                "format": SCHEMA,
                "think": False,
                "stream": False,
                "keep_alive": "60m",
                "options": {"temperature": 0, "num_ctx": 4096},
            },
        )
        wall = (time.perf_counter() - start) * 1000
        eval_count = out.get("eval_count", 0)
        eval_s = out.get("eval_duration", 0) / 1e9
        print(
            f"[{attempt}] wall={wall:.0f}ms load={out.get('load_duration', 0) / 1e6:.0f}ms "
            f"prompt_tokens={out.get('prompt_eval_count')} out_tokens={eval_count} "
            f"tok/s={eval_count / eval_s if eval_s else 0:.1f}"
        )
        print("   content:", out["message"]["content"])
        if out["message"].get("thinking"):
            print("   WARNING: thinking text returned despite think=false")


if __name__ == "__main__":
    main()
