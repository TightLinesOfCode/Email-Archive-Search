import email
import json
from datetime import datetime, timezone

from email.utils import parsedate_to_datetime

from config import EMAILS_DIR, FETCH_DATE_FROM, FETCH_DATE_TO, FETCH_LIMIT, POP_LEAVE_DAYS, POP_LEAVE_ON_SERVER, READ_ONLY
from pop_client import connect, delete_message, fetch_headers, fetch_raw, get_message_uids
from email_parser import parse_email
from archiver import is_archived, save_email


def _in_date_range(headers_bytes: bytes) -> bool:
    """Return True if the email's Date header falls within the configured range."""
    if FETCH_DATE_FROM is None and FETCH_DATE_TO is None:
        return True
    try:
        msg = email.message_from_bytes(headers_bytes)
        email_date = parsedate_to_datetime(msg.get("Date", "")).date()
    except Exception:
        return True  # unparseable date — include rather than silently drop

    if FETCH_DATE_FROM and email_date < FETCH_DATE_FROM:
        return False
    if FETCH_DATE_TO and email_date > FETCH_DATE_TO:
        return False
    return True


def _should_delete(uid: str) -> bool:
    if not POP_LEAVE_ON_SERVER:
        return True
    if POP_LEAVE_DAYS == 0:
        return False
    email_json = EMAILS_DIR / uid / "email.json"
    try:
        with open(email_json, encoding="utf-8") as fh:
            data = json.load(fh)
        archived_at = datetime.fromisoformat(data["archived_at"])
        age_days = (datetime.now(timezone.utc) - archived_at).days
        return age_days >= POP_LEAVE_DAYS
    except Exception:
        return False


def fetch_and_archive() -> dict:
    """
    Connect to POP3, fetch new messages, and archive them to disk.
    Returns a summary dict: total_on_server, new, skipped, deleted, errors.
    """
    EMAILS_DIR.mkdir(parents=True, exist_ok=True)

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

            already_archived = is_archived(EMAILS_DIR, uid)

            if not already_archived:
                try:
                    # Check date range before downloading the full message
                    if FETCH_DATE_FROM or FETCH_DATE_TO:
                        headers = fetch_headers(conn, msg_num)
                        if not _in_date_range(headers):
                            skipped_count += 1
                            continue

                    raw = fetch_raw(conn, msg_num)
                    email_dict, attachment_files = parse_email(raw, uid)
                    save_email(EMAILS_DIR, uid, email_dict, attachment_files)
                    new_count += 1
                except Exception as e:
                    errors.append(f"{uid}: {e}")
                    continue
            else:
                skipped_count += 1

            if not READ_ONLY and _should_delete(uid):
                delete_message(conn, msg_num)
                deleted_count += 1
    finally:
        conn.quit()

    return {
        "total_on_server": total,
        "new": new_count,
        "skipped": skipped_count,
        "deleted": deleted_count,
        "errors": errors,
    }
