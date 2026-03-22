import imaplib
import re

from config import EMAIL_ADDRESS, EMAIL_PASSWORD, IMAP_HOST, IMAP_PORT, IMAP_USE_SSL

# Virtual Gmail labels that mirror other folders — skip to avoid duplicates
_SKIP_FOLDERS = {
    "[Gmail]/All Mail",
    "[Gmail]/Important",
    "[Gmail]/Starred",
    "[Google Mail]/All Mail",
    "[Google Mail]/Important",
    "[Google Mail]/Starred",
}


def connect() -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    if IMAP_USE_SSL:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    else:
        conn = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    conn.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    return conn


def list_folders(conn: imaplib.IMAP4_SSL | imaplib.IMAP4) -> list[str]:
    """Return all folder names, excluding virtual Gmail aggregation labels."""
    _status, items = conn.list()
    folders = []
    for item in items:
        decoded = item.decode("utf-8", errors="replace")
        # LIST response format: (\Flags) "delimiter" "folder name"
        match = re.search(r'"[/\\]"\s+"?(.+?)"?\s*$', decoded)
        if not match:
            match = re.search(r'NIL\s+"?(.+?)"?\s*$', decoded)
        if match:
            name = match.group(1).strip().strip('"')
            if name not in _SKIP_FOLDERS:
                folders.append(name)
    return folders


def sanitize_folder(name: str) -> str:
    """Convert an IMAP folder name into a safe directory name."""
    name = name.replace("[Gmail]/", "Gmail_")
    name = name.replace("[Google Mail]/", "Google_Mail_")
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def get_uids(conn: imaplib.IMAP4_SSL | imaplib.IMAP4, folder: str) -> list[str]:
    """Select a folder (read-only) and return all message UIDs."""
    status, _data = conn.select(f'"{folder}"', readonly=True)
    if status != "OK":
        return []
    status, data = conn.uid("SEARCH", "ALL")  # type: ignore[arg-type]
    if status != "OK" or not data or not data[0]:
        return []
    raw = data[0].decode()
    return raw.split() if raw.strip() else []


def fetch_raw(conn: imaplib.IMAP4_SSL | imaplib.IMAP4, uid: str) -> bytes:
    """Fetch the full RFC-822 message bytes for a UID."""
    status, data = conn.uid("FETCH", uid, "(RFC822)")  # type: ignore[arg-type]
    if status != "OK" or not data or data[0] is None:
        raise RuntimeError(f"Failed to fetch UID {uid}")
    return data[0][1]


def fetch_headers(conn: imaplib.IMAP4_SSL | imaplib.IMAP4, uid: str) -> bytes:
    """Fetch only the headers for a UID (much faster than the full message)."""
    status, data = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER])")  # type: ignore[arg-type]
    if status != "OK" or not data or data[0] is None:
        raise RuntimeError(f"Failed to fetch headers for UID {uid}")
    return data[0][1]


def get_uids_in_date_range(
    conn: imaplib.IMAP4_SSL | imaplib.IMAP4,
    folder: str,
    date_from=None,
    date_to=None,
) -> list[str]:
    """Select a folder (read-write) and return UIDs matching the date range."""
    status, _data = conn.select(f'"{folder}"', readonly=False)
    if status != "OK":
        return []
    criteria: list[str] = []
    if date_from:
        # IMAP SINCE is inclusive; format: DD-Mon-YYYY
        criteria.append(f"SINCE {date_from.strftime('%d-%b-%Y')}")
    if date_to:
        # IMAP BEFORE is exclusive (day after desired end)
        from datetime import timedelta
        before = date_to + timedelta(days=1)
        criteria.append(f"BEFORE {before.strftime('%d-%b-%Y')}")
    search_arg = " ".join(criteria) if criteria else "ALL"
    status, data = conn.uid("SEARCH", search_arg)  # type: ignore[arg-type]
    if status != "OK" or not data or not data[0]:
        return []
    raw = data[0].decode()
    return raw.split() if raw.strip() else []


def delete_uid(conn: imaplib.IMAP4_SSL | imaplib.IMAP4, uid: str) -> None:
    """Mark a message as \\Deleted by UID."""
    conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")  # type: ignore[arg-type]


def expunge_folder(conn: imaplib.IMAP4_SSL | imaplib.IMAP4) -> None:
    """Expunge all \\Deleted messages from the currently selected folder."""
    conn.expunge()
