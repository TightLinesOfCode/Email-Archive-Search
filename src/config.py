import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Account credentials
# ---------------------------------------------------------------------------
EMAIL_ADDRESS = os.environ["EMAIL_ADDRESS"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------
_protocol = os.environ.get("MAIL_PROTOCOL", "IMAP").strip().upper()
if _protocol not in ("IMAP", "POP3"):
    raise ValueError(f"MAIL_PROTOCOL={_protocol!r} must be IMAP or POP3.")
MAIL_PROTOCOL = _protocol

# ---------------------------------------------------------------------------
# IMAP settings  (used when MAIL_PROTOCOL=IMAP)
# ---------------------------------------------------------------------------
IMAP_HOST    = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT    = int(os.environ.get("IMAP_PORT", "993"))
IMAP_USE_SSL = os.environ.get("IMAP_USE_SSL", "true").lower() == "true"

# ---------------------------------------------------------------------------
# POP3 settings  (used when MAIL_PROTOCOL=POP3)
# ---------------------------------------------------------------------------
POP_HOST    = os.environ.get("POP_HOST", "pop.gmail.com")
POP_PORT    = int(os.environ.get("POP_PORT", "995"))
POP_USE_SSL = os.environ.get("POP_USE_SSL", "true").lower() == "true"

# Server retention — how long to leave messages on the POP3 server
LEAVE_ON_SERVER = os.environ.get("LEAVE_ON_SERVER", "true").lower() == "true"
LEAVE_DAYS      = int(os.environ.get("LEAVE_DAYS", "365"))

# ---------------------------------------------------------------------------
# SMTP settings
# ---------------------------------------------------------------------------
SMTP_HOST    = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Fetch behaviour  (shared across protocols)
# ---------------------------------------------------------------------------

def _parse_date(key: str) -> date | None:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{key}={raw!r} is not a valid date — use YYYY-MM-DD format.")

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

FETCH_DATE_FROM: date | None = _parse_date("FETCH_DATE_FROM")
FETCH_DATE_TO:   date | None = _parse_date("FETCH_DATE_TO")
FETCH_LIMIT:     int | None  = _parse_fetch_limit("FETCH_LIMIT")
READ_ONLY = os.environ.get("READ_ONLY", "true").lower() == "true"

# Seconds to wait between fetching individual emails.
# Gmail's IMAP rate limit is roughly 1 connection with ~1 request/second sustained.
# 1.0 is a safe default; reduce to 0.5 only on non-Gmail servers.
FETCH_DELAY: float = float(os.environ.get("FETCH_DELAY", "1.0"))

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent   # src/config.py → repo root
_data_dir_raw = Path(os.environ.get("DATA_DIR", "pop-email-archive"))
DATA_DIR = _data_dir_raw if _data_dir_raw.is_absolute() else _REPO_ROOT / _data_dir_raw
ACCOUNT_DIR = DATA_DIR / EMAIL_ADDRESS   # e.g. <repo>/pop-email-archive/you@gmail.com
# Emails are stored at ACCOUNT_DIR/<folder>/<uid>/email.json
