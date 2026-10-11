import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

DB_PATH = Path(os.environ.get("FIELDPILOT_DB", BACKEND_DIR / "fieldpilot.db"))
AUDIO_DIR = Path(os.environ.get("FIELDPILOT_AUDIO_DIR", DATA_DIR / "audio"))
PHOTO_DIR = Path(os.environ.get("FIELDPILOT_PHOTO_DIR", DATA_DIR / "photos"))
CHECKLIST_PATH = Path(os.environ.get("FIELDPILOT_CHECKLIST", DATA_DIR / "checklist.json"))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("FIELDPILOT_MODEL", "qwen3:4b")
NUM_CTX = int(os.environ.get("FIELDPILOT_NUM_CTX", "4096"))
KEEP_ALIVE = os.environ.get("FIELDPILOT_KEEP_ALIVE", "60m")
LLM_TIMEOUT_S = float(os.environ.get("FIELDPILOT_LLM_TIMEOUT", "180"))

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
WHISPER_CLI = os.environ.get("WHISPER_CLI", "whisper-cli")
WHISPER_MODEL = Path(os.environ.get("WHISPER_MODEL", REPO_DIR / "models" / "ggml-base.en.bin"))

FRONTEND_DIST = REPO_DIR / "frontend" / "dist"
