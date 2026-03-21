import poplib

from config import EMAIL_ADDRESS, EMAIL_PASSWORD, POP_HOST, POP_PORT, POP_USE_SSL


def connect() -> poplib.POP3_SSL | poplib.POP3:
    if POP_USE_SSL:
        conn = poplib.POP3_SSL(POP_HOST, POP_PORT)
    else:
        conn = poplib.POP3(POP_HOST, POP_PORT)
    conn.user(EMAIL_ADDRESS)
    conn.pass_(EMAIL_PASSWORD)
    return conn


def get_message_uids(conn: poplib.POP3_SSL | poplib.POP3) -> list[tuple[int, str]]:
    """Return (msg_num, uid) pairs via UIDL so we can skip already-archived messages."""
    _response, listings, _size = conn.uidl()
    result = []
    for item in listings:
        parts = item.decode().split(" ", 1)
        result.append((int(parts[0]), parts[1].strip()))
    return result


def fetch_headers(conn: poplib.POP3_SSL | poplib.POP3, msg_num: int) -> bytes:
    """Fetch only the headers of a message (no body) using the TOP command."""
    _response, lines, _octets = conn.top(msg_num, 0)
    return b"\r\n".join(lines)


def fetch_raw(conn: poplib.POP3_SSL | poplib.POP3, msg_num: int) -> bytes:
    """Fetch the full raw RFC-822 bytes for a message number."""
    _response, lines, _octets = conn.retr(msg_num)
    return b"\r\n".join(lines)


def delete_message(conn: poplib.POP3_SSL | poplib.POP3, msg_num: int) -> None:
    """Mark a message for deletion. Deletion is finalised on QUIT."""
    conn.dele(msg_num)
