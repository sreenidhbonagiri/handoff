# Handoff

Offline job-closeout assistant. Typed or spoken observations go to a local model (Ollama, qwen3:4b), which proposes structured facts. Application code validates every proposal, checks a sample closeout procedure, asks one follow-up question, and builds an evidence-linked report. No cloud inference.

## One-time setup (needs internet)

```
brew install ollama whisper-cpp
ollama serve &                      # or open the Ollama app
ollama pull qwen3:4b
mkdir -p models && curl -L -o models/ggml-base.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm install)
python3 scripts/smoke_ollama.py     # verifies think=false + JSON schema, prints latency
```

## Run (works offline)

```
cd backend && ../.venv/bin/uvicorn app.main:app --port 8000     # terminal 1
cd frontend && npm run dev                                      # terminal 2, open http://127.0.0.1:5173
```

For the demo, `cd frontend && npm run build` lets the backend serve the UI at http://127.0.0.1:8000.

## Tests and evaluation

```
.venv/bin/python -m unittest discover backend/tests              # deterministic validator/checklist
.venv/bin/python evals/run_eval.py                                # dev cases, Handoff vs one-pass baseline
```

## Ownership

- Inference and state: `backend/app/{main,schemas,db,llm,state,checklist,report,pipeline}.py`, `backend/data/`, `evals/dev/`, `evals/*.py`
- UI and evidence: `frontend/**`, `backend/app/transcribe.py`, `evals/fresh/`
- Contract: `backend/app/schemas.py`, mirrored by hand in `frontend/src/types.ts`
