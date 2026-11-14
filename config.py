from pathlib import Path
import os
APP_NAME = "FiscalOps Requirement Studio"
VERSION = "8.0.1"
EDITION = "Stable"
HOST = "127.0.0.1"
PORT = 6969
MAX_PDF_MB = 50
MAX_PAGES = 500
BASE_DIR = Path(__file__).resolve().parent
LEGACY_DATA = any(path.is_file() for path in (
    *BASE_DIR.glob("work/*/workspace.json"),
    *BASE_DIR.glob("work/jobs/*/job.json"),
    *BASE_DIR.glob("data/companies/*/profile.json"),
    *BASE_DIR.glob("data/templates/*/*.docx"),
    *BASE_DIR.glob("corrections_store/*.json*"),
))
LOCAL_DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SSGT" / "FiscalOps"
DATA_ROOT = Path(os.environ.get("FISCALOPS_DATA_DIR") or (BASE_DIR if LEGACY_DATA else LOCAL_DATA)).expanduser().resolve()
WORK_DIR = DATA_ROOT / "work"

AUTOSAVE_SECONDS = 20
SESSION_RETENTION_DAYS = 30

ENTERPRISE_DIR = DATA_ROOT / "data"
CORRECTIONS_DIR = DATA_ROOT / "corrections_store"

JOB_DIR = WORK_DIR / "jobs"

# Local-only hybrid document intelligence.  Disabled by default so the
# existing deterministic/PaddleOCR flow remains the safe compatibility path.
OLLAMA_ENABLED = os.environ.get("FISCALOPS_OLLAMA_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
OLLAMA_URL = os.environ.get("FISCALOPS_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("FISCALOPS_OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = float(os.environ.get("FISCALOPS_OLLAMA_TIMEOUT", "120"))
OLLAMA_RETRIES = max(0, int(os.environ.get("FISCALOPS_OLLAMA_RETRIES", "1")))
OLLAMA_BLOCK_SIZE = max(1000, int(os.environ.get("FISCALOPS_OLLAMA_BLOCK_SIZE", "12000")))
OLLAMA_OVERLAP = max(0, int(os.environ.get("FISCALOPS_OLLAMA_OVERLAP", "800")))
