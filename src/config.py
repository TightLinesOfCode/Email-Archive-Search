import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

POP_HOST = os.environ.get("POP_HOST", "pop.gmail.com")
POP_PORT = int(os.environ.get("POP_PORT", "995"))
POP_USE_SSL = os.environ.get("POP_USE_SSL", "true").lower() == "true"
POP_LEAVE_ON_SERVER = os.environ.get("POP_LEAVE_ON_SERVER", "true").lower() == "true"
POP_LEAVE_DAYS = int(os.environ.get("POP_LEAVE_DAYS", "365"))
READ_ONLY = os.environ.get("READ_ONLY", "true").lower() == "true"

def _parse_fetch_limit(key: str) -> int | None:
    raw = os.environ.get(key, "10").strip().upper()
    if raw == "ALL":
        return None
    try:
        value = int(raw)
        if value < 1:
            raise ValueError
        return value
    except ValueError:
        raise ValueError(f"{key}={raw!r} must be a positive integer or ALL.")

FETCH_LIMIT: int | None = _parse_fetch_limit("FETCH_LIMIT")

def _parse_date(key: str) -> date | None:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{key}={raw!r} is not a valid date — use YYYY-MM-DD format.")

FETCH_DATE_FROM: date | None = _parse_date("FETCH_DATE_FROM")
FETCH_DATE_TO:   date | None = _parse_date("FETCH_DATE_TO")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

EMAIL_ADDRESS = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

DATA_DIR = Path(os.environ.get("DATA_DIR", "/pop-email-archive"))
ACCOUNT_DIR = DATA_DIR / EMAIL_ADDRESS   # e.g. /pop-email-archive/you@gmail.com
EMAILS_DIR  = ACCOUNT_DIR / "emails"
