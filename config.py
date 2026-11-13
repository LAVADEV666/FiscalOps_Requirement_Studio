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
