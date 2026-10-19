"""Project paths and the sample files that sit next to this repo."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PROJECT_DB_PATH = DATA_DIR / "bskuw.duckdb"
UPLOAD_DIR = DATA_DIR / "uploads"

# The working database stays off the project folder. This repo lives on Google
# Drive, and Drive locks a DuckDB file while it syncs it.
_LOCAL_BASE = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
LOCAL_DATA_DIR = Path(_LOCAL_BASE) / "BSKUW"
DB_PATH = LOCAL_DATA_DIR / "bskuw.duckdb"

PARENT = ROOT.parent
DEFAULT_TRACKING = (
    PARENT
    / "Tracking Basket SKU reports"
    / "data - 2026-10-15T202405.651.A-used.26_16-26_41.xlsx"
)
DEFAULT_QUANT = Path(r"D:\Anton\UTires\Total Qty\quant_report\261015\quants_catalog_general-2026-10-15.csv")
