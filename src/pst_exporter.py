"""
PST / EML Exporter

Converts the local JSON email archive into formats that can be imported into Outlook.

  PST  — Outlook Personal Storage Table, single file  (requires: pip install pypff)
  EML  — one .eml file per email, folder structure preserved  (no extra dependencies)

Outlook import instructions:
  PST:  File → Open & Export → Import/Export → Import from another program or file
  EML:  drag the folder of .eml files into an Outlook folder, or use
        File → Open & Export → Import/Export → Import Internet Mail and Addresses
"""

import json
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Callable


# ── Address helpers ────────────────────────────────────────────────────────────

def _fmt_addr(addr: dict | None) -> str:
    """Format a {'name': ..., 'address': ...} dict as 'Name <email>'."""
    if not addr:
        return ""
    name    = (addr.get("name")    or "").strip()
    address = (addr.get("address") or "").strip()
    if name and address:
        return f"{name} <{address}>"
    return address or name


def _fmt_addr_list(addrs: list[dict]) -> str:
    return ", ".join(filter(None, (_fmt_addr(a) for a in addrs)))


def _to_datetime(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None


# ── EML export ─────────────────────────────────────────────────────────────────

def export_to_eml(
    input_dir: Path,
    output_dir: Path,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> dict:
    """
    Write each archived email as an individual .eml file.

    Output mirrors the archive layout:
        output_dir/<folder>/<uid>.eml

    Returns {"total": N, "folders": N, "errors": [...]}.
    """
    email_jsons = sorted(input_dir.glob("*/*/email.json"))
    total       = len(email_jsons)
    errors:  list[str] = []
    folders: set[str]  = set()

    for n, json_path in enumerate(email_jsons, 1):
        folder_name = ""
        subject     = ""
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)

            folder_name = data.get("folder") or json_path.parent.parent.name
            uid         = json_path.parent.name
            subject     = data.get("subject") or ""
            folders.add(folder_name)

            msg = EmailMessage()
            msg["Subject"]    = subject
            msg["From"]       = _fmt_addr(data.get("from"))
            msg["To"]         = _fmt_addr_list(data.get("to")  or [])
            msg["Cc"]         = _fmt_addr_list(data.get("cc")  or [])
            msg["Message-ID"] = data.get("message_id") or ""

            dt = _to_datetime(data.get("date") or "")
            if dt:
                msg["Date"] = format_datetime(dt)

            body = data.get("body") or {}
            text = body.get("text") or ""
            html = body.get("html") or ""

            if text:
                msg.set_content(text)
            if html:
                if text:
                    msg.add_alternative(html, subtype="html")
                else:
                    msg.set_content(html, subtype="html")

            # Attach files
            email_dir = json_path.parent
            for att in data.get("attachments") or []:
                att_path = email_dir / (att.get("path") or "")
                if att_path.exists():
                    raw_ct  = att.get("content_type") or "application/octet-stream"
                    maintype, _, subtype = raw_ct.partition("/")
                    msg.add_attachment(
                        att_path.read_bytes(),
                        maintype=maintype,
                        subtype=subtype or "octet-stream",
                        filename=att.get("filename") or att_path.name,
                    )

            out_path = output_dir / folder_name / f"{uid}.eml"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(msg.as_bytes())

        except Exception as exc:
            errors.append(f"{json_path}: {exc}")

        if on_progress:
            on_progress(n, total, folder_name, subject)

    return {"total": total - len(errors), "folders": len(folders), "errors": errors}


# ── PST export ─────────────────────────────────────────────────────────────────

_PYPFF_INSTALL = (
    "  pypff is required for PST export.\n\n"
    "  Install:  pip install pypff\n\n"
    "  Note: pypff wraps the libpff C library.  You may also need the native lib:\n"
    "    Debian/Ubuntu:  sudo apt install libpff-dev\n"
    "    macOS:          brew install libpff\n"
    "    Windows:        pre-built wheels are available via pip on most Python versions\n\n"
    "  Alternatively choose EML export — no extra dependencies required."
)


def pypff_available() -> bool:
    try:
        import pypff  # noqa: F401
        return True
    except ImportError:
        return False


def export_to_pst(
    input_dir: Path,
    output_path: Path,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> dict:
    """
    Write all archived emails into a single Outlook .pst file.

    Requires: pip install pypff

    Returns {"total": N, "folders": N, "errors": [...]}.
    """
    try:
        import pypff
    except ImportError:
        raise ImportError(_PYPFF_INSTALL)

    email_jsons = sorted(input_dir.glob("*/*/email.json"))
    total       = len(email_jsons)
    errors:     list[str] = []
    folder_map: dict[str, object] = {}

    pst  = pypff.file()
    pst.open_write(str(output_path))
    root = pst.get_root_folder()

    for n, json_path in enumerate(email_jsons, 1):
        folder_name = ""
        subject     = ""
        try:
            with open(json_path, encoding="utf-8") as fh:
                data = json.load(fh)

            folder_name = data.get("folder") or json_path.parent.parent.name
            subject     = data.get("subject") or ""

            if folder_name not in folder_map:
                folder_map[folder_name] = root.add_sub_folder(folder_name)

            pst_folder = folder_map[folder_name]
            message    = pst_folder.add_message()

            message.set_subject(subject)

            from_info = data.get("from") or {}
            message.set_sender_name(from_info.get("name") or "")
            message.set_sender_email_address(from_info.get("address") or "")

            to_list = data.get("to") or []
            if to_list:
                message.set_received_by_name(to_list[0].get("name") or "")
                message.set_received_by_email_address(to_list[0].get("address") or "")

            body = data.get("body") or {}
            if body.get("text"):
                message.set_plain_text_body(body["text"])
            if body.get("html"):
                message.set_html_body(body["html"])

            dt = _to_datetime(data.get("date") or "")
            if dt:
                message.set_client_submit_time(dt)

        except Exception as exc:
            errors.append(f"{json_path}: {exc}")

        if on_progress:
            on_progress(n, total, folder_name, subject)

    pst.close()
    return {"total": total - len(errors), "folders": len(folder_map), "errors": errors}


# ── Interactive CLI ────────────────────────────────────────────────────────────

W = 70


def _rule(char: str = "─") -> str:
    return char * W


def _section(title: str) -> None:
    print(f"\n{_rule()}")
    print(f"  {title}")
    print(_rule())


def _prompt_path(label: str, must_exist: bool = False) -> Path:
    while True:
        try:
            raw = input(f"  {label}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if not raw:
            print("    Path cannot be empty.")
            continue
        p = Path(raw).expanduser()
        if must_exist and not p.exists():
            print(f"    Path does not exist: {p}")
            continue
        return p


def _prompt_format() -> str:
    """Ask the user which export format to use. Returns 'pst' or 'eml'."""
    has_pypff = pypff_available()

    print("\n  Export format:")
    print("  1) PST  — single Outlook .pst file", end="")
    if not has_pypff:
        print("  (pypff not installed — see below)")
    else:
        print()
    print("  2) EML  — one .eml file per email, organised by folder")

    if not has_pypff:
        print(f"\n{_PYPFF_INSTALL}")

    while True:
        try:
            choice = input("  Select [1/2]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise
        if choice == "1":
            if not has_pypff:
                print("  pypff is not installed.  Please install it first or choose EML.")
                continue
            return "pst"
        if choice == "2":
            return "eml"
        print("  Please enter 1 or 2.")


def run_pst_export() -> bool:
    """
    Interactive PST/EML export.  Prompts for paths and format, then runs the export.
    Returns True on success.
    """
    _section("Export to Outlook (PST / EML)")

    print("\n  This tool converts your local email archive to a format")
    print("  that can be imported directly into Microsoft Outlook.\n")

    try:
        fmt = _prompt_format()

        print()
        input_dir = _prompt_path(
            "Archive folder to export  (e.g. pop-email-archive/you@gmail.com)",
            must_exist=True,
        )

        if fmt == "pst":
            output_path = _prompt_path("Output .pst file path  (e.g. outlook-export.pst)")
            if output_path.suffix.lower() != ".pst":
                output_path = output_path.with_suffix(".pst")
        else:
            output_path = _prompt_path("Output folder for .eml files  (will be created if needed)")

    except (EOFError, KeyboardInterrupt):
        print("  Cancelled.")
        return False

    # Count emails
    email_jsons = list(input_dir.glob("*/*/email.json"))
    total = len(email_jsons)

    if total == 0:
        print(f"\n  No emails found under {input_dir}")
        return False

    print(f"\n  Found {total:,} email{'s' if total != 1 else ''} in {input_dir}")
    print(f"  Output: {output_path}")

    try:
        confirm = input("\n  Proceed? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return False

    if confirm != "y":
        print("  Aborted.")
        return False

    # Progress display
    w = len(str(total))
    print()

    def on_progress(n: int, tot: int, folder: str, subject: str) -> None:
        f_col = f"{folder:<20}"[:20]
        s_col = (subject[:46] + "…") if len(subject) > 47 else f"{subject:<47}"
        print(f"  [{n:>{w}}/{tot}]  {f_col}  {s_col}")

    try:
        if fmt == "pst":
            result = export_to_pst(input_dir, output_path, on_progress=on_progress)
        else:
            result = export_to_eml(input_dir, output_path, on_progress=on_progress)
    except ImportError as exc:
        print(f"\n  {exc}")
        return False
    except KeyboardInterrupt:
        print("\n\n  Interrupted — output may be incomplete.")
        return False
    except Exception as exc:
        print(f"\n  Export failed: {exc}")
        return False

    n_err = len(result["errors"])
    fmt_label = "PST" if fmt == "pst" else "EML"
    print(
        f"\n  Done.  {result['total']:,} email{'s' if result['total'] != 1 else ''} exported "
        f"across {result['folders']} folder{'s' if result['folders'] != 1 else ''} "
        f"({fmt_label}),  {n_err} error{'s' if n_err != 1 else ''}."
    )
    if result["errors"]:
        print("\n  Errors:")
        for err in result["errors"]:
            print(f"    • {err}")

    return True
