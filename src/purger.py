import json
from datetime import date
from pathlib import Path
from typing import Callable

from config import ACCOUNT_DIR, MAIL_PROTOCOL, READ_ONLY
from email_parser import parse_email
from imap_client import (
    connect,
    delete_uid,
    expunge_folder,
    fetch_raw,
    get_uids_in_date_range,
    list_folders,
    sanitize_folder,
)

# Fields that are deliberately different between the server copy and the local
# copy (archival timestamp, local UID, folder name).  Everything else must match.
_IGNORE_FIELDS = {"archived_at", "id", "folder"}


def _load_stored(folder: str, uid: str) -> dict | None:
    """Load the locally archived email.json, or None if missing/unreadable."""
    email_json = ACCOUNT_DIR / folder / uid / "email.json"
    try:
        with open(email_json, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _emails_match(server_dict: dict, stored_dict: dict) -> bool:
    """
    Return True if the server-parsed email dict and the locally stored dict
    are identical for every field except those in _IGNORE_FIELDS.
    """
    for key, server_val in server_dict.items():
        if key in _IGNORE_FIELDS:
            continue
        if server_val != stored_dict.get(key):
            return False
    return True


def _attachments_match(
    folder: str,
    uid: str,
    server_attachments: list[tuple[str, bytes]],
) -> tuple[bool, str]:
    """
    Byte-for-byte comparison of every attachment decoded from the server
    against the corresponding file on disk.

    Returns (True, "") on a full match, or (False, reason) on any mismatch.
    """
    attachments_dir = ACCOUNT_DIR / folder / uid / "attachments"

    # Build a filename → bytes map from the server payload
    server_map: dict[str, bytes] = {}
    for filename, content in server_attachments:
        safe_name = Path(filename).name
        server_map[safe_name] = content

    # Build the same map from disk
    local_map: dict[str, bytes] = {}
    if attachments_dir.exists():
        for path in attachments_dir.iterdir():
            if path.is_file():
                local_map[path.name] = path.read_bytes()

    if set(server_map) != set(local_map):
        return False, (
            f"attachment name sets differ — "
            f"server={sorted(server_map)}, local={sorted(local_map)}"
        )

    for name, server_bytes in server_map.items():
        local_bytes = local_map[name]
        if server_bytes != local_bytes:
            return False, (
                f"attachment {name!r} bytes differ — "
                f"server {len(server_bytes)} bytes, local {len(local_bytes)} bytes"
            )

    return True, ""


def purge_server(
    date_from: date | None = None,
    date_to: date | None = None,
    on_progress: Callable | None = None,
) -> dict:
    """
    For each IMAP folder, find messages in the given date range that are
    already archived locally.  For each candidate:

      1. Download the full raw email from the server.
      2. Parse it with parse_email() into a structured dict.
      3. Compare every meaningful field against the stored email.json.
      4. Only mark \\Deleted (and expunge) if they match exactly.

    Returns a summary dict: deleted, skipped, folders_scanned, errors.
    """
    if MAIL_PROTOCOL != "IMAP":
        raise RuntimeError("Purge Server is only available for IMAP accounts.")
    if READ_ONLY:
        raise RuntimeError("READ_ONLY is enabled — server cannot be modified.")

    conn = connect()
    deleted = 0
    skipped = 0
    folders_scanned = 0
    errors: list[str] = []

    try:
        folders = list_folders(conn)
        for raw_folder in folders:
            folder = sanitize_folder(raw_folder)
            folders_scanned += 1

            try:
                uids = get_uids_in_date_range(conn, raw_folder, date_from, date_to)
            except Exception as e:
                errors.append(f"Could not list {raw_folder}: {e}")
                continue

            to_delete: list[str] = []
            for uid in uids:
                # Only consider messages we have archived locally
                stored = _load_stored(folder, uid)
                if stored is None:
                    skipped += 1
                    continue

                # Download the full message from the server
                try:
                    raw = fetch_raw(conn, uid)
                except Exception as e:
                    errors.append(f"{folder}/{uid}: download failed: {e}")
                    skipped += 1
                    continue

                # Parse the server copy the same way the archiver does
                try:
                    server_dict, server_attachments = parse_email(raw, uid, folder=folder)
                except Exception as e:
                    errors.append(f"{folder}/{uid}: parse failed: {e}")
                    skipped += 1
                    continue

                # Compare every meaningful metadata field
                if not _emails_match(server_dict, stored):
                    skipped += 1
                    errors.append(
                        f"{folder}/{uid}: content mismatch — skipped "
                        f"(subject: server={server_dict.get('subject')!r}, "
                        f"local={stored.get('subject')!r})"
                    )
                    continue

                # Byte-for-byte attachment comparison
                match, reason = _attachments_match(folder, uid, server_attachments)
                if not match:
                    skipped += 1
                    errors.append(f"{folder}/{uid}: attachment mismatch — skipped ({reason})")
                    continue

                to_delete.append(uid)

            # Mark all verified UIDs as \Deleted, then expunge once per folder
            for uid in to_delete:
                try:
                    delete_uid(conn, uid)
                    deleted += 1
                    if on_progress:
                        on_progress(deleted, folder, uid, "")
                except Exception as e:
                    errors.append(f"{folder}/{uid}: delete failed: {e}")

            if to_delete:
                try:
                    expunge_folder(conn)
                except Exception as e:
                    errors.append(f"Expunge {raw_folder}: {e}")

    finally:
        conn.logout()

    return {
        "deleted": deleted,
        "skipped": skipped,
        "folders_scanned": folders_scanned,
        "errors": errors,
    }
