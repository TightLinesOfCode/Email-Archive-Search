import email
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime


def _decode_str(value: str | None) -> str:
    """Decode an RFC-2047 encoded header value into a plain string."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for fragment, charset in parts:
        if isinstance(fragment, bytes):
            decoded.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(fragment)
    return "".join(decoded)


def _parse_address(value: str | None) -> dict | None:
    if not value:
        return None
    name, address = parseaddr(value)
    address = address.strip().lower()
    if not address:
        return None
    return {"name": _decode_str(name), "address": address}


def _parse_address_list(value: str | None) -> list[dict]:
    if not value:
        return []
    return [
        {"name": _decode_str(name), "address": addr.strip().lower()}
        for name, addr in getaddresses([value])
        if addr.strip()
    ]


def parse_email(raw: bytes, uid: str, folder: str = "") -> tuple[dict, list[tuple[str, bytes]]]:
    """
    Parse raw RFC-822 bytes into a structured dict suitable for JSON serialisation.

    Returns:
        (email_dict, [(filename, content_bytes), ...])
    """
    msg = email.message_from_bytes(raw)

    # --- Date ---
    date_str = msg.get("Date", "")
    try:
        date = parsedate_to_datetime(date_str).isoformat()
    except Exception:
        date = date_str

    archived_at = datetime.now(timezone.utc).isoformat()

    # --- Walk MIME parts ---
    text_body: str | None = None
    html_body: str | None = None
    attachments_meta: list[dict] = []
    attachment_files: list[tuple[str, bytes]] = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        raw_filename = part.get_filename()
        filename = _decode_str(raw_filename) if raw_filename else None

        is_attachment = disposition == "attachment" or (
            filename and content_type not in ("text/plain", "text/html")
        )

        if is_attachment and filename:
            payload = part.get_payload(decode=True)
            if payload is not None:
                attachment_files.append((filename, payload))
                attachments_meta.append({
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(payload),
                    "path": f"attachments/{filename}",
                })

        elif content_type == "text/plain" and text_body is None and not filename:
            payload = part.get_payload(decode=True)
            if payload is not None:
                charset = part.get_content_charset() or "utf-8"
                text_body = payload.decode(charset, errors="replace")

        elif content_type == "text/html" and html_body is None and not filename:
            payload = part.get_payload(decode=True)
            if payload is not None:
                charset = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

    email_dict = {
        "id": uid,
        "folder": folder,
        "message_id": msg.get("Message-ID", "").strip(),
        "archived_at": archived_at,
        "date": date,
        "from": _parse_address(msg.get("From")),
        "to": _parse_address_list(msg.get("To")),
        "cc": _parse_address_list(msg.get("Cc")),
        "reply_to": _parse_address(msg.get("Reply-To")),
        "subject": _decode_str(msg.get("Subject")),
        "body": {
            "text": text_body,
            "html": html_body,
        },
        "has_attachments": bool(attachments_meta),
        "attachments": attachments_meta,
    }

    return email_dict, attachment_files
