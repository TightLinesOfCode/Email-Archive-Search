"""
Email Archive — main entry point.

Interactive mode (no arguments):
    python main.py

Non-interactive mode (run an operation directly):
    python main.py fetch
    python main.py purge
    python main.py both
    python main.py web

Common options:
    --protocol IMAP|POP3          Mail protocol (or set MAIL_PROTOCOL env var)
    --date-from YYYY-MM-DD        Fetch emails on/after this date
    --date-to   YYYY-MM-DD        Fetch emails on/before this date
    --limit     N|ALL             Max emails to fetch (default 10, ALL for unlimited)
    --delay     SECS              Seconds between fetched emails (default 1.0)
    --purge-from YYYY-MM-DD       Purge emails on/after this date
    --purge-to   YYYY-MM-DD       Purge emails on/before this date
    --port      PORT              Web app port (default 5000)
    --yes, -y                     Skip confirmation prompts
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from fetch_cli import (
    BANNER,
    _prompt_protocol,
    _purge_available,
    _rule,
    _show_config,
    _show_purge_notice,
    run_fetch,
    run_purge,
)
from pst_exporter import run_pst_export


# ── Argument parser ────────────────────────────────────────────────────────────

def _date(value: str) -> str:
    """Validate a YYYY-MM-DD date string for argparse."""
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date {value!r} — use YYYY-MM-DD")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Email Archive — fetch, purge, or browse your email archive.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "When no operation is given the interactive menu is shown.\n"
            "All options can also be set via environment variables (see .env-example)."
        ),
    )

    p.add_argument(
        "operation",
        nargs="?",
        choices=["fetch", "purge", "both", "export", "web"],
        metavar="OPERATION",
        help="fetch | purge | both | export | web  (omit to enter the interactive menu)",
    )

    # ── Protocol ──────────────────────────────────────────────────────────────
    p.add_argument(
        "--protocol", "-p",
        choices=["IMAP", "POP3"],
        metavar="IMAP|POP3",
        help="Mail protocol (default: from MAIL_PROTOCOL env var or prompted)",
    )

    # ── Fetch options ─────────────────────────────────────────────────────────
    fetch = p.add_argument_group("fetch options")
    fetch.add_argument(
        "--date-from",
        type=_date,
        metavar="YYYY-MM-DD",
        help="Fetch emails on or after this date  (sets FETCH_DATE_FROM)",
    )
    fetch.add_argument(
        "--date-to",
        type=_date,
        metavar="YYYY-MM-DD",
        help="Fetch emails on or before this date  (sets FETCH_DATE_TO)",
    )
    fetch.add_argument(
        "--limit",
        metavar="N|ALL",
        help="Max emails to fetch  (sets FETCH_LIMIT; use ALL for unlimited)",
    )
    fetch.add_argument(
        "--delay",
        type=float,
        metavar="SECS",
        help="Seconds between fetched emails  (sets FETCH_DELAY, default 1.0)",
    )

    # ── Purge options ─────────────────────────────────────────────────────────
    purge = p.add_argument_group("purge options")
    purge.add_argument(
        "--purge-from",
        type=_date,
        metavar="YYYY-MM-DD",
        help="Purge emails on or after this date  (sets PURGE_DATE_FROM)",
    )
    purge.add_argument(
        "--purge-to",
        type=_date,
        metavar="YYYY-MM-DD",
        help="Purge emails on or before this date  (sets PURGE_DATE_TO)",
    )

    # ── Web options ───────────────────────────────────────────────────────────
    web = p.add_argument_group("web options")
    web.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        help="Web app port  (sets PORT, default 5000)",
    )

    # ── Behaviour ─────────────────────────────────────────────────────────────
    p.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompts (non-interactive / scripted use)",
    )

    return p


# ── Helpers ────────────────────────────────────────────────────────────────────

def _apply_args_to_env(args: argparse.Namespace) -> None:
    """Write CLI args into environment variables so config/fetch_cli pick them up."""
    if args.protocol:
        os.environ["MAIL_PROTOCOL"] = args.protocol.upper()
    if args.date_from:
        os.environ["FETCH_DATE_FROM"] = args.date_from
    if args.date_to:
        os.environ["FETCH_DATE_TO"] = args.date_to
    if args.limit:
        os.environ["FETCH_LIMIT"] = args.limit.upper()
    if args.delay is not None:
        os.environ["FETCH_DELAY"] = str(args.delay)
    if args.purge_from:
        os.environ["PURGE_DATE_FROM"] = args.purge_from
    if args.purge_to:
        os.environ["PURGE_DATE_TO"] = args.purge_to
    if args.port:
        os.environ["PORT"] = str(args.port)


def _launch_web() -> None:
    from web.app import app

    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Starting web app at http://localhost:{port}")
    print("  Press Ctrl-C to stop.\n")
    try:
        app.run(host="0.0.0.0", port=port, threaded=True)
    except KeyboardInterrupt:
        print("\n\n  Web app stopped.")


# ── Interactive menu ───────────────────────────────────────────────────────────

def _main_menu(purge_ok: bool) -> str:
    """Display the main menu and return the chosen action."""
    print(f"\n{_rule()}")
    print("  Main Menu")
    print(_rule())
    print("  1) Fetch        — download new emails into the local archive")
    print("  2) Purge        — delete archived emails from the IMAP server")
    print("  3) Both         — fetch first, then purge")
    print("  4) Export       — export archive to Outlook PST or EML")
    print("  5) Switch to Web App")
    print("  6) Exit")

    if not purge_ok:
        print("\n  (Options 2 and 3 are disabled — see configuration above)")

    while True:
        try:
            choice = input("\nSelect [1-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "exit"

        if choice == "1":
            return "fetch"
        if choice == "2":
            if not purge_ok:
                print("  Purge is not available with the current configuration.")
                continue
            return "purge"
        if choice == "3":
            if not purge_ok:
                print("  Purge is not available with the current configuration.")
                continue
            return "both"
        if choice == "4":
            return "export"
        if choice == "5":
            return "web"
        if choice == "6":
            return "exit"
        print("  Please enter 1–6.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    args = _build_parser().parse_args()

    # Push CLI args into env vars before any config/fetch_cli imports
    _apply_args_to_env(args)

    print(BANNER)

    # Protocol — respects MAIL_PROTOCOL env var (set above if --protocol was given)
    protocol = _prompt_protocol()
    os.environ["MAIL_PROTOCOL"] = protocol

    # Config summary
    try:
        _show_config(protocol)
    except Exception as e:
        print(f"\nConfiguration error: {e}")
        sys.exit(1)

    purge_ok = _purge_available()
    if not purge_ok:
        _show_purge_notice()

    # --yes: auto-confirm all prompts by patching _confirm in fetch_cli
    if args.yes:
        import fetch_cli
        fetch_cli._confirm = lambda prompt: True

    # ── Non-interactive: operation given as argument ───────────────────────────
    if args.operation:
        op = args.operation
        if op in ("purge", "both") and not purge_ok:
            print("\nPurge is not available with the current configuration (see above).")
            sys.exit(1)
        try:
            if op == "web":
                _launch_web()
            elif op == "export":
                run_pst_export()
            else:
                if op in ("fetch", "both"):
                    run_fetch()
                if op in ("purge", "both"):
                    run_purge()
        except KeyboardInterrupt:
            print("\n\nCancelled.")
            sys.exit(0)
        return

    # ── Interactive: menu loop ────────────────────────────────────────────────
    while True:
        action = _main_menu(purge_ok)

        if action == "exit":
            print(f"\n{_rule()}")
            print("  Goodbye.")
            print(_rule())
            break

        if action == "web":
            _launch_web()
            break  # exit after the web app stops

        if action == "export":
            run_pst_export()
        if action in ("fetch", "both"):
            run_fetch()
        if action in ("purge", "both"):
            run_purge()

        try:
            input(f"\n  Press Enter to return to the main menu…")
        except (EOFError, KeyboardInterrupt):
            print()
            break


if __name__ == "__main__":
    main()
