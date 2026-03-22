import email as email_lib
import json
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from config import (
    ACCOUNT_DIR,
    FETCH_DATE_FROM,
    FETCH_DATE_TO,
    FETCH_DELAY,
    FETCH_LIMIT,
    MAIL_PROTOCOL,
    LEAVE_DAYS,
    LEAVE_ON_SERVER,
    READ_ONLY,
)
from email_parser import parse_email
from archiver import is_archived, save_email


def _in_date_range(headers_bytes: bytes) -> bool:
    """Return True if the email's Date header falls within the configured range."""
    if FETCH_DATE_FROM is None and FETCH_DATE_TO is None:
        return True
    try:
        msg = email_lib.message_from_bytes(headers_bytes)
        email_date = parsedate_to_datetime(msg.get("Date", "")).date()
    except Exception:
        return True  # unparseable date — include rather than silently drop
    if FETCH_DATE_FROM and email_date < FETCH_DATE_FROM:
        return False
    if FETCH_DATE_TO and email_date > FETCH_DATE_TO:
        return False
    return True


# ---------------------------------------------------------------------------
# IMAP fetch
# ---------------------------------------------------------------------------

def _fetch_imap(on_progress: Callable | None = None) -> dict:
    from imap_client import (
        connect, fetch_headers, fetch_raw, get_uids, list_folders, sanitize_folder,
    )

    ACCOUNT_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    folders_scanned = 0
    new_count = 0
    skipped_count = 0
    errors: list[str] = []

    try:
        folders = list_folders(conn)
        for raw_folder in folders:
            folder = sanitize_folder(raw_folder)
            folders_scanned += 1
            try:
                uids = get_uids(conn, raw_folder)
            except Exception as e:
                errors.append(f"Could not list {raw_folder}: {e}")
                continue

            for uid in uids:
                if FETCH_LIMIT is not None and new_count >= FETCH_LIMIT:
                    break
                if is_archived(ACCOUNT_DIR, folder, uid):
                    skipped_count += 1
                    continue
                try:
                    if FETCH_DATE_FROM or FETCH_DATE_TO:
                        if not _in_date_range(fetch_headers(conn, uid)):
                            skipped_count += 1
                            continue
                    raw = fetch_raw(conn, uid)
                    email_dict, attachment_files = parse_email(raw, uid, folder=folder)
                    save_email(ACCOUNT_DIR, folder, uid, email_dict, attachment_files)
                    new_count += 1
                    if on_progress:
                        on_progress(new_count, folder, uid, email_dict.get("subject") or "")
                    time.sleep(FETCH_DELAY)
                except Exception as e:
                    errors.append(f"{folder}/{uid}: {e}")
    finally:
        conn.logout()

    return {
        "protocol": "IMAP",
        "folders_scanned": folders_scanned,
        "new": new_count,
        "skipped": skipped_count,
        "deleted": 0,
        "errors": errors,
        "read_only": READ_ONLY,
    }


# ---------------------------------------------------------------------------
# POP3 fetch
# ---------------------------------------------------------------------------

def _should_delete_pop(uid: str, folder: str) -> bool:
    if not LEAVE_ON_SERVER:
        return True
    if LEAVE_DAYS == 0:
        return False
    email_json = ACCOUNT_DIR / folder / uid / "email.json"
    try:
        with open(email_json, encoding="utf-8") as fh:
            data = json.load(fh)
        archived_at = datetime.fromisoformat(data["archived_at"])
        age_days = (datetime.now(timezone.utc) - archived_at).days
        return age_days >= LEAVE_DAYS
    except Exception:
        return False


def _fetch_pop3(on_progress: Callable | None = None) -> dict:
    from pop_client import (
        connect, delete_message, fetch_headers, fetch_raw, get_message_uids,
    )

    FOLDER = "INBOX"
    ACCOUNT_DIR.mkdir(parents=True, exist_ok=True)
    conn = connect()
    new_count = 0
    skipped_count = 0
    deleted_count = 0
    errors: list[str] = []
    total = 0

    try:
        uids = get_message_uids(conn)
        total = len(uids)

        for msg_num, uid in uids:
            if FETCH_LIMIT is not None and new_count >= FETCH_LIMIT:
                break

            already_archived = is_archived(ACCOUNT_DIR, FOLDER, uid)

            if not already_archived:
                try:
                    if FETCH_DATE_FROM or FETCH_DATE_TO:
                        if not _in_date_range(fetch_headers(conn, msg_num)):
                            skipped_count += 1
                            continue
                    raw = fetch_raw(conn, msg_num)
                    email_dict, attachment_files = parse_email(raw, uid, folder=FOLDER)
                    save_email(ACCOUNT_DIR, FOLDER, uid, email_dict, attachment_files)
                    new_count += 1
                    if on_progress:
                        on_progress(new_count, FOLDER, uid, email_dict.get("subject") or "")
                    time.sleep(FETCH_DELAY)
                except Exception as e:
                    errors.append(f"{uid}: {e}")
                    continue
            else:
                skipped_count += 1

            if not READ_ONLY and _should_delete_pop(uid, FOLDER):
                delete_message(conn, msg_num)
                deleted_count += 1
    finally:
        conn.quit()

    return {
        "protocol": "POP3",
        "folders_scanned": 1,
        "new": new_count,
        "skipped": skipped_count,
        "deleted": deleted_count,
        "total_on_server": total,
        "errors": errors,
        "read_only": READ_ONLY,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_and_archive(on_progress: Callable | None = None) -> dict:
    """Fetch and archive emails using whichever protocol is set in MAIL_PROTOCOL."""
    if MAIL_PROTOCOL == "IMAP":
        return _fetch_imap(on_progress=on_progress)
    return _fetch_pop3(on_progress=on_progress)


# ---------------------------------------------------------------------------
# Preview / count (no downloading)
# ---------------------------------------------------------------------------

def _count_new_imap() -> dict:
    from imap_client import connect, fetch_headers, get_uids, list_folders, sanitize_folder

    conn = connect()
    new_count = 0
    total_on_server = 0
    folders_scanned = 0
    try:
        folders = list_folders(conn)
        for raw_folder in folders:
            folder = sanitize_folder(raw_folder)
            folders_scanned += 1
            try:
                uids = get_uids(conn, raw_folder)
                total_on_server += len(uids)
                for uid in uids:
                    if FETCH_DATE_FROM or FETCH_DATE_TO:
                        try:
                            if not _in_date_range(fetch_headers(conn, uid)):
                                continue
                        except Exception:
                            pass
                    if not is_archived(ACCOUNT_DIR, folder, uid):
                        new_count += 1
            except Exception:
                pass
    finally:
        conn.logout()

    return {
        "protocol": "IMAP",
        "new": new_count,
        "total_on_server": total_on_server,
        "already_archived": total_on_server - new_count,
        "folders_scanned": folders_scanned,
        "fetch_limit": FETCH_LIMIT,
    }


def _count_new_pop3() -> dict:
    from pop_client import connect, fetch_headers, get_message_uids

    FOLDER = "INBOX"
    conn = connect()
    new_count = 0
    total_on_server = 0
    try:
        uids = get_message_uids(conn)
        total_on_server = len(uids)
        for msg_num, uid in uids:
            if FETCH_DATE_FROM or FETCH_DATE_TO:
                try:
                    if not _in_date_range(fetch_headers(conn, msg_num)):
                        continue
                except Exception:
                    pass
            if not is_archived(ACCOUNT_DIR, FOLDER, uid):
                new_count += 1
    finally:
        conn.quit()

    return {
        "protocol": "POP3",
        "new": new_count,
        "total_on_server": total_on_server,
        "already_archived": total_on_server - new_count,
        "folders_scanned": 1,
        "fetch_limit": FETCH_LIMIT,
    }


def count_new() -> dict:
    """Connect to the mail server and count new emails without downloading anything."""
    if MAIL_PROTOCOL == "IMAP":
        return _count_new_imap()
    return _count_new_pop3()
