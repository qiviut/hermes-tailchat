from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("TAILCHAT_DB_PATH", str(BASE_DIR / "tailchat.db")))
HERMES_API_BASE_URL = os.getenv("HERMES_API_BASE_URL", "http://127.0.0.1:8642").rstrip("/")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
APP_TITLE = "Hermes Tailchat"
