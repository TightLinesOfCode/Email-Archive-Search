#!/usr/bin/env python3
"""
Headless CLI for fetching and purging emails without the web app.

Usage:
    python fetch_cli.py [fetch|purge|both]

    If no argument is given you will be prompted to choose.

Environment variables (via .env or shell):
    EMAIL_ADDRESS, EMAIL_PASSWORD  — required
    MAIL_PROTOCOL                  — IMAP or POP3 (prompted if not set)
    IMAP_HOST / POP_HOST           — mail server hostname
    IMAP_PORT / POP_PORT           — mail server port
    DATA_DIR                       — archive root  (default: <repo>/pop-email-archive)
    FETCH_DELAY                    — seconds between emails  (default 1.0)
    FETCH_LIMIT                    — max emails to fetch     (default 10, ALL for unlimited)
    FETCH_DATE_FROM                — only fetch on/after this date  (YYYY-MM-DD)
    FETCH_DATE_TO                  — only fetch on/before this date (YYYY-MM-DD)
    READ_ONLY                      — true/false; must be false to purge (default true)
    LEAVE_ON_SERVER                — keep messages on POP3 server     (default true)
    LEAVE_DAYS                     — days before deleting from server  (default 365)
"""

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

# ── Formatting helpers ────────────────────────────────────────────────────────

W = 70   # banner width

BANNER = f"""
╔{'═' * (W - 2)}╗
║{'Email Archive — Headless CLI':^{W - 2}}║
╚{'═' * (W - 2)}╝"""


def _rule(char: str = "─") -> str:
    return char * W


def _section(title: str) -> None:
    print(f"\n{_rule()}")
    print(f"  {title}")
    print(_rule())


def _row(label: str, value: str, warn: bool = False) -> None:
    prefix = "  ⚠  " if warn else "     "
    print(f"{prefix}{label:<28}{value}")


def _fmt(n: int) -> str:
    return f"{n:,}"


def _estimate(count: int, delay: float) -> str:
    if count == 0:
        return "nothing to do"
    secs = count * delay
    if secs < 10:
        return "a few seconds"
    if secs < 90:
        return f"~{int(secs)} seconds"
    return f"~{secs / 60:.1f} minutes"


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _prompt_protocol() -> str:
    existing = os.environ.get("MAIL_PROTOCOL", "").strip().upper()
    if existing in ("IMAP", "POP3"):
        return existing
    print("\nMAIL_PROTOCOL is not set.")
    print("  1) IMAP — archives all folders")
    print("  2) POP3 — archives inbox only")
    while True:
        choice = input("Select [1/2]: ").strip()
        if choice == "1":
            return "IMAP"
        if choice == "2":
            return "POP3"
        print("  Please enter 1 or 2.")


def _prompt_date(label: str, env_key: str) -> "date | None":
    existing = os.environ.get(env_key, "").strip()
    if existing:
        try:
            return date.fromisoformat(existing)
        except ValueError:
            pass
    while True:
        raw = input(f"  {label} [YYYY-MM-DD or Enter to skip]: ").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print("    Invalid date — use YYYY-MM-DD.")


def _prompt_operation(purge_available: bool) -> str:
    """Return 'fetch', 'purge', or 'both'."""
    if purge_available:
        options = {"1": "fetch", "2": "purge", "3": "both"}
        print("\n  1) Fetch   — download new emails into the local archive")
        print("  2) Purge   — delete archived emails from the IMAP server")
        print("  3) Both    — fetch first, then purge")
        while True:
            choice = input("Select operation [1/2/3]: ").strip()
            if choice in options:
                return options[choice]
            print("  Please enter 1, 2, or 3.")
    else:
        print("\n  1) Fetch   — download new emails into the local archive")
        print("  (Purge is disabled — see configuration notice above)")
        input("Press Enter to continue with Fetch, or Ctrl-C to cancel: ")
        return "fetch"


# ── Config display ────────────────────────────────────────────────────────────

def _show_config(protocol: str) -> None:
    """Import config and print a full summary. Returns nothing; exits on error."""
    from config import (
        ACCOUNT_DIR, DATA_DIR, EMAIL_ADDRESS,
        FETCH_DATE_FROM, FETCH_DATE_TO, FETCH_DELAY, FETCH_LIMIT,
        IMAP_HOST, IMAP_PORT, IMAP_USE_SSL,
        LEAVE_DAYS, LEAVE_ON_SERVER, MAIL_PROTOCOL,
        POP_HOST, POP_PORT, POP_USE_SSL,
        READ_ONLY,
    )

    _section("Configuration")

    # Account
    _row("Email account",    EMAIL_ADDRESS)
    _row("Protocol",         MAIL_PROTOCOL)

    # Server
    if MAIL_PROTOCOL == "IMAP":
        ssl_label = "SSL" if IMAP_USE_SSL else "plain"
        _row("IMAP server",  f"{IMAP_HOST}:{IMAP_PORT}  ({ssl_label})")
    else:
        ssl_label = "SSL" if POP_USE_SSL else "plain"
        _row("POP3 server",  f"{POP_HOST}:{POP_PORT}  ({ssl_label})")

    print()

    # Paths
    _row("Archive root",     str(DATA_DIR))
    _row("Account folder",   str(ACCOUNT_DIR))

    # Count existing emails
    count = sum(1 for _ in ACCOUNT_DIR.glob("*/*/email.json")) if ACCOUNT_DIR.exists() else 0
    _row("Emails archived",  _fmt(count))

    print()

    # Fetch settings
    limit_label  = str(FETCH_LIMIT) if FETCH_LIMIT is not None else "ALL"
    from_label   = str(FETCH_DATE_FROM) if FETCH_DATE_FROM else "—"
    to_label     = str(FETCH_DATE_TO)   if FETCH_DATE_TO   else "—"

    _row("Fetch limit",      f"{limit_label}  (FETCH_LIMIT)")
    _row("Fetch rate",       f"{FETCH_DELAY}s per email  (FETCH_DELAY)")
    _row("Date from",        f"{from_label}  (FETCH_DATE_FROM)")
    _row("Date to",          f"{to_label}  (FETCH_DATE_TO)")

    print()

    # Server-side behaviour
    _row("Read-only mode",   f"{'yes' if READ_ONLY else 'NO — server can be modified'}",
         warn=not READ_ONLY)
    if MAIL_PROTOCOL == "POP3":
        leave_label = f"{'yes' if LEAVE_ON_SERVER else 'no'}  (LEAVE_ON_SERVER)"
        _row("Leave on server", leave_label)
        if LEAVE_ON_SERVER and LEAVE_DAYS:
            _row("Delete after",  f"{LEAVE_DAYS} days  (LEAVE_DAYS)")


def _purge_available() -> bool:
    from config import MAIL_PROTOCOL, READ_ONLY
    return MAIL_PROTOCOL == "IMAP" and not READ_ONLY


def _show_purge_notice() -> None:
    from config import MAIL_PROTOCOL, READ_ONLY
    reasons = []
    if MAIL_PROTOCOL != "IMAP":
        reasons.append(f"MAIL_PROTOCOL={MAIL_PROTOCOL!r}  →  must be IMAP")
    if READ_ONLY:
        reasons.append("READ_ONLY=true  →  must be false")
    if reasons:
        print()
        print("  ⚠  Purge is not available:")
        for r in reasons:
            print(f"       • {r}")


# ── Fetch operation ───────────────────────────────────────────────────────────

def run_fetch() -> bool:
    """Prompt for dates, count, confirm, then fetch. Returns True on success."""
    from config import FETCH_DELAY, FETCH_LIMIT, MAIL_PROTOCOL

    _section("Fetch — Download new emails")

    print("\n  Date range to fetch (leave blank to use env / fetch all):")
    date_from = _prompt_date("Start date (FETCH_DATE_FROM)", "FETCH_DATE_FROM")
    date_to   = _prompt_date("End date   (FETCH_DATE_TO)",   "FETCH_DATE_TO")
    if date_from:
        os.environ["FETCH_DATE_FROM"] = date_from.isoformat()
    if date_to:
        os.environ["FETCH_DATE_TO"] = date_to.isoformat()

    # Re-import to pick up the new env vars
    import importlib, config as _cfg
    importlib.reload(_cfg)
    from fetcher import count_new

    print(f"\n  Connecting to server …")
    try:
        info = count_new()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        return False
    except Exception as e:
        print(f"\n  Could not connect: {e}")
        return False

    will_fetch = info["new"]
    if FETCH_LIMIT is not None:
        will_fetch = min(will_fetch, FETCH_LIMIT)

    limit_label = str(FETCH_LIMIT) if FETCH_LIMIT is not None else "ALL"

    print()
    _row("Folders scanned",   _fmt(info["folders_scanned"]))
    _row("Total on server",   _fmt(info["total_on_server"]))
    _row("Already archived",  _fmt(info["already_archived"]))

    new_label = _fmt(info["new"])
    if FETCH_LIMIT is not None and info["new"] > FETCH_LIMIT:
        new_label += f"  (capped to {FETCH_LIMIT} by FETCH_LIMIT)"
    _row("New to download",   new_label)
    _row("Fetch limit",       limit_label)

    if info.get("server_date_from") or info.get("server_date_to"):
        _row("Server date range",
             f"{info.get('server_date_from') or '?'} → {info.get('server_date_to') or '?'}")
    if date_from or date_to:
        _row("Fetch date filter",
             f"{date_from or 'beginning'} → {date_to or 'today'}")

    _row("Estimated time",    _estimate(will_fetch, FETCH_DELAY))

    print(f"\n  ✓  LOCAL ARCHIVE ONLY — nothing on the {MAIL_PROTOCOL} server will be "
          "modified or deleted.")

    if will_fetch == 0:
        print("\n  Nothing to fetch — archive is already up to date.")
        return True

    print()
    if not _confirm(f"  Download {_fmt(will_fetch)} email{'s' if will_fetch != 1 else ''}? [y/N]: "):
        print("  Aborted.")
        return False

    # Run fetch with live progress
    from fetcher import fetch_and_archive
    w = len(str(will_fetch))
    print()

    def on_progress(n: int, folder: str, uid: str, subject: str) -> None:
        f_col = f"{folder:<20}"[:20]
        s_col = (subject[:48] + "…") if len(subject) > 49 else f"{subject:<49}"
        print(f"  [{n:>{w}}/{will_fetch}]  {f_col}  {s_col}")

    try:
        result = fetch_and_archive(on_progress=on_progress)
    except KeyboardInterrupt:
        print("\n\n  Interrupted — partial results may have been saved.")
        return False

    n_err = len(result["errors"])
    print(f"\n  Done.  {_fmt(result['new'])} new "
          f"email{'s' if result['new'] != 1 else ''} archived,  "
          f"{n_err} error{'s' if n_err != 1 else ''}.")
    if result.get("deleted"):
        print(f"         {_fmt(result['deleted'])} message"
              f"{'s' if result['deleted'] != 1 else ''} removed from server.")
    if result["errors"]:
        print("\n  Errors:")
        for err in result["errors"]:
            print(f"    • {err}")
    return True


# ── Purge operation ───────────────────────────────────────────────────────────

def run_purge() -> bool:
    """Prompt for dates, confirm (twice), then purge. Returns True on success."""
    _section("Purge — Delete archived emails from the IMAP server")

    print()
    print("  ⚠  WARNING: This permanently deletes emails from your IMAP server.")
    print("     Only emails already in your local archive with an exactly")
    print("     matching Message-ID (and identical content) will be removed.")
    print("     This cannot be undone.")

    print("\n  Date range to purge (leave blank to purge all archived emails):")
    date_from = _prompt_date("Start date", "PURGE_DATE_FROM")
    date_to   = _prompt_date("End date  ", "PURGE_DATE_TO")

    range_desc = "all dates"
    if date_from or date_to:
        range_desc = f"{date_from or 'beginning'} → {date_to or 'today'}"

    print()
    _row("Purge date range", range_desc)
    _row("Verification",     "full download + byte-level content match required")
    _row("Server effect",    "matched emails will be permanently deleted", warn=True)

    print()
    if not _confirm("  Proceed with purge? [y/N]: "):
        print("  Aborted.")
        return False

    print()
    if not _confirm("  ⚠  Are you absolutely sure? This cannot be undone. [y/N]: "):
        print("  Aborted.")
        return False

    from purger import purge_server
    print()

    deleted_count = [0]

    def on_progress(n: int, folder: str, uid: str, _subject: str) -> None:
        deleted_count[0] = n
        print(f"  [{n}]  {folder:<24}  uid {uid}")

    try:
        result = purge_server(
            date_from=date_from,
            date_to=date_to,
            on_progress=on_progress,
        )
    except KeyboardInterrupt:
        print("\n\n  Interrupted — some messages may have already been deleted.")
        return False
    except Exception as e:
        print(f"\n  Purge failed: {e}")
        return False

    n_err = len(result["errors"])
    print(f"\n  Done.  {_fmt(result['deleted'])} email"
          f"{'s' if result['deleted'] != 1 else ''} deleted from server,  "
          f"{_fmt(result['skipped'])} skipped,  "
          f"{n_err} error{'s' if n_err != 1 else ''}.")
    if result["errors"]:
        print("\n  Errors / mismatches:")
        for err in result["errors"]:
            print(f"    • {err}")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)

    # 1. Protocol — set before importing config
    protocol = _prompt_protocol()
    os.environ["MAIL_PROTOCOL"] = protocol

    # 2. Show full config summary
    try:
        _show_config(protocol)
    except Exception as e:
        print(f"\nConfiguration error: {e}")
        sys.exit(1)

    # 3. Purge availability notice
    purge_ok = _purge_available()
    if not purge_ok:
        _show_purge_notice()

    # 4. Choose operation (or accept from argv)
    if len(sys.argv) > 1:
        op = sys.argv[1].lower()
        if op not in ("fetch", "purge", "both"):
            print(f"\nUnknown operation {op!r}. Use: fetch, purge, or both.")
            sys.exit(1)
        if op in ("purge", "both") and not purge_ok:
            print("\nPurge is not available with the current configuration (see above).")
            sys.exit(1)
        print(f"\n  Operation: {op}  (from command line)")
    else:
        try:
            op = _prompt_operation(purge_ok)
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(0)

    print()

    # 5. Run
    try:
        if op in ("fetch", "both"):
            if not run_fetch():
                sys.exit(1)

        if op in ("purge", "both"):
            if not run_purge():
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)

    print(f"\n{_rule()}")
    print("  All done.")
    print(_rule())


if __name__ == "__main__":
    main()
