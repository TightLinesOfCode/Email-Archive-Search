#!/usr/bin/env python3
"""
Standalone CLI for fetching and archiving emails without the web app.

Usage:
    python fetch_cli.py

Environment variables (via .env or shell):
    EMAIL_ADDRESS, EMAIL_PASSWORD  — required
    MAIL_PROTOCOL                  — IMAP or POP3 (prompted if not set)
    FETCH_DELAY                    — seconds between emails (default 1.0)
    FETCH_LIMIT                    — max emails to fetch (default 10, ALL for unlimited)
    DATA_DIR                       — archive location (default ./pop-email-archive)
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

# ── Helpers ──────────────────────────────────────────────────────────────────

HEADER = """
╔══════════════════════════════════════╗
║       Email Archive — Fetcher        ║
╚══════════════════════════════════════╝
"""


def _prompt_protocol() -> str:
    existing = os.environ.get("MAIL_PROTOCOL", "").strip().upper()
    if existing in ("IMAP", "POP3"):
        print(f"Protocol : {existing}  (from environment)")
        return existing
    print("Select protocol:")
    print("  1) IMAP  — archives all folders")
    print("  2) POP3  — archives inbox only")
    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            return "IMAP"
        if choice == "2":
            return "POP3"
        print("  Please enter 1 or 2.")


def _prompt_date(label: str, env_key: str) -> date | None:
    existing = os.environ.get(env_key, "").strip()
    if existing:
        try:
            d = date.fromisoformat(existing)
            print(f"{label}: {d}  (from environment)")
            return d
        except ValueError:
            pass
    while True:
        raw = input(f"{label} [YYYY-MM-DD or Enter to skip]: ").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print("  Invalid date — use YYYY-MM-DD format.")


def _estimate_time(count: int, delay: float) -> str:
    if count == 0:
        return "nothing to download"
    secs = count * delay
    if secs < 10:
        return "a few seconds"
    if secs < 90:
        return f"~{int(secs)} seconds"
    mins = secs / 60
    return f"~{mins:.1f} minutes"


def _fmt(n: int) -> str:
    return f"{n:,}"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(HEADER)

    # 1. Protocol
    protocol = _prompt_protocol()
    os.environ["MAIL_PROTOCOL"] = protocol

    # 2. Date range
    print()
    date_from = _prompt_date("Start date", "FETCH_DATE_FROM")
    date_to   = _prompt_date("End date  ", "FETCH_DATE_TO")
    if date_from:
        os.environ["FETCH_DATE_FROM"] = date_from.isoformat()
    if date_to:
        os.environ["FETCH_DATE_TO"] = date_to.isoformat()

    # 3. Import now so config picks up the env vars we just set
    from config import FETCH_DELAY, FETCH_LIMIT, IMAP_HOST, POP_HOST, MAIL_PROTOCOL as PROTO
    from fetcher import count_new, fetch_and_archive

    host = IMAP_HOST if PROTO == "IMAP" else POP_HOST
    limit_label = str(FETCH_LIMIT) if FETCH_LIMIT is not None else "ALL"

    # 4. Count new emails
    print(f"\nConnecting to {host} …")
    try:
        info = count_new()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"\nCould not connect: {e}")
        sys.exit(1)

    will_fetch = info["new"]
    if FETCH_LIMIT is not None:
        will_fetch = min(will_fetch, FETCH_LIMIT)

    # 5. Summary
    col = 22
    print()
    print(f"  {'Folders scanned':<{col}}: {_fmt(info['folders_scanned'])}")
    print(f"  {'Total on server':<{col}}: {_fmt(info['total_on_server'])}")
    print(f"  {'Already archived':<{col}}: {_fmt(info['already_archived'])}")
    print(f"  {'New to download':<{col}}: {_fmt(info['new'])}", end="")
    if FETCH_LIMIT is not None and info["new"] > FETCH_LIMIT:
        print(f"  (capped to {FETCH_LIMIT} by FETCH_LIMIT)", end="")
    print()
    print(f"  {'Fetch limit':<{col}}: {limit_label}")
    print(f"  {'Rate limit':<{col}}: {FETCH_DELAY}s per email  (FETCH_DELAY)")
    print(f"  {'Estimated time':<{col}}: {_estimate_time(will_fetch, FETCH_DELAY)}")

    date_range = ""
    if date_from or date_to:
        date_range = f"  (date filter: {date_from or '—'} → {date_to or '—'})"
    print(f"\n  ⚠  LOCAL ARCHIVE ONLY — nothing on the {PROTO} server will be"
          f" modified or deleted.{date_range}")

    if will_fetch == 0:
        print("\nNothing to fetch. Your archive is already up to date.")
        return

    # 6. Confirm
    print()
    answer = input(
        f"Download {_fmt(will_fetch)} email{'s' if will_fetch != 1 else ''}? [y/N]: "
    ).strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    # 7. Fetch with live progress
    w = len(str(will_fetch))
    print()

    def on_progress(n: int, folder: str, uid: str, subject: str) -> None:
        folder_col = f"{folder:<20}"[:20]
        subj_col   = (subject[:50] + "…") if len(subject) > 51 else f"{subject:<51}"
        print(f"  [{n:>{w}}/{will_fetch}]  {folder_col}  {subj_col}")

    try:
        result = fetch_and_archive(on_progress=on_progress)
    except KeyboardInterrupt:
        print("\n\nInterrupted — partial results may have been saved.")
        sys.exit(1)

    # 8. Final summary
    n_err = len(result["errors"])
    print(f"\nDone.  {_fmt(result['new'])} new email{'s' if result['new'] != 1 else ''} "
          f"archived,  {n_err} error{'s' if n_err != 1 else ''}.")
    if result.get("deleted"):
        print(f"       {_fmt(result['deleted'])} message{'s' if result['deleted'] != 1 else ''} "
              f"removed from server.")
    if result["errors"]:
        print("\nErrors:")
        for err in result["errors"]:
            print(f"  • {err}")


if __name__ == "__main__":
    main()
