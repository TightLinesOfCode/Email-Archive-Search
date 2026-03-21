import json
import sqlite3
from datetime import datetime, timezone

from config import ACCOUNT_DIR, EMAILS_DIR

INDEX_DB = ACCOUNT_DIR / "search.db"


def _connect() -> sqlite3.Connection:
    INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row
    return conn


def create_index(comprehensive: bool = False) -> dict:
    """
    Build (or rebuild) the search index from all archived emails.

    Simple:        subject, sender, recipients
    Comprehensive: + full body text, attachment filenames
    """
    conn = _connect()
    cur = conn.cursor()

    cur.executescript("""
        DROP TABLE IF EXISTS emails_fts;
        DROP TABLE IF EXISTS emails_meta;
        DROP TABLE IF EXISTS index_settings;
    """)

    cur.execute("""
        CREATE TABLE index_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE emails_meta (
            uid              TEXT PRIMARY KEY,
            subject          TEXT,
            from_name        TEXT,
            from_address     TEXT,
            to_addresses     TEXT,
            date             TEXT,
            archived_at      TEXT,
            has_attachments  INTEGER DEFAULT 0,
            attachment_names TEXT
        )
    """)

    if comprehensive:
        cur.execute("""
            CREATE VIRTUAL TABLE emails_fts USING fts5(
                uid              UNINDEXED,
                subject,
                from_name,
                from_address,
                to_addresses,
                body_text,
                attachment_names
            )
        """)
    else:
        cur.execute("""
            CREATE VIRTUAL TABLE emails_fts USING fts5(
                uid          UNINDEXED,
                subject,
                from_name,
                from_address,
                to_addresses
            )
        """)

    index_type = "comprehensive" if comprehensive else "simple"
    cur.execute("INSERT INTO index_settings VALUES ('type', ?)", (index_type,))
    cur.execute(
        "INSERT INTO index_settings VALUES ('created_at', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )

    indexed = 0
    errors: list[str] = []

    if EMAILS_DIR.exists():
        for email_json in sorted(EMAILS_DIR.glob("*/email.json")):
            try:
                with open(email_json, encoding="utf-8") as fh:
                    d = json.load(fh)

                uid = d.get("id") or email_json.parent.name
                subject = d.get("subject") or ""
                from_info = d.get("from") or {}
                from_name = from_info.get("name") or ""
                from_address = from_info.get("address") or ""
                to_list = d.get("to") or []
                to_addresses = " ".join(t.get("address", "") for t in to_list)
                date = d.get("date") or ""
                archived_at = d.get("archived_at") or ""
                has_attachments = 1 if d.get("has_attachments") else 0
                attachment_names = " ".join(
                    a.get("filename", "") for a in (d.get("attachments") or [])
                )
                body_text = ((d.get("body") or {}).get("text") or "")

                cur.execute(
                    "INSERT OR REPLACE INTO emails_meta VALUES (?,?,?,?,?,?,?,?,?)",
                    (uid, subject, from_name, from_address, to_addresses,
                     date, archived_at, has_attachments, attachment_names),
                )

                if comprehensive:
                    cur.execute(
                        "INSERT INTO emails_fts VALUES (?,?,?,?,?,?,?)",
                        (uid, subject, from_name, from_address, to_addresses,
                         body_text, attachment_names),
                    )
                else:
                    cur.execute(
                        "INSERT INTO emails_fts VALUES (?,?,?,?,?)",
                        (uid, subject, from_name, from_address, to_addresses),
                    )

                indexed += 1
            except Exception as e:
                errors.append(f"{email_json.parent.name}: {e}")

    conn.commit()
    conn.close()
    return {"indexed": indexed, "errors": errors, "comprehensive": comprehensive}


def search(query: str) -> list[dict]:
    """Search the FTS index. Returns matching email metadata dicts."""
    if not INDEX_DB.exists():
        return []
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT m.uid, m.subject, m.from_name, m.from_address,
                   m.to_addresses, m.date, m.has_attachments, m.attachment_names
            FROM emails_fts f
            JOIN emails_meta m ON m.uid = f.uid
            WHERE emails_fts MATCH ?
            ORDER BY rank
            """,
            (query,),
        )
        return [dict(row) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def archive_stats() -> dict:
    """
    Scan all archived email.json files and return heuristics:
    total count, earliest date, latest date, attachment counts.
    Does not require the search index to exist.
    """
    if not EMAILS_DIR.exists():
        return {
            "total": 0,
            "date_from": None,
            "date_to": None,
            "with_attachments": 0,
            "total_attachments": 0,
        }

    dates = []
    with_attachments = 0
    total_attachments = 0

    for email_json in EMAILS_DIR.glob("*/email.json"):
        try:
            with open(email_json, encoding="utf-8") as fh:
                d = json.load(fh)
            raw_date = d.get("date") or ""
            if raw_date:
                dates.append(raw_date)
            if d.get("has_attachments"):
                with_attachments += 1
                total_attachments += len(d.get("attachments") or [])
        except Exception:
            pass

    dates.sort()
    return {
        "total": len(dates),
        "date_from": dates[0][:10] if dates else None,
        "date_to": dates[-1][:10] if dates else None,
        "with_attachments": with_attachments,
        "total_attachments": total_attachments,
    }


def index_status() -> dict:
    """Return metadata about the current index."""
    if not INDEX_DB.exists():
        return {"exists": False, "count": 0, "type": None, "created_at": None}
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM emails_meta")
        count = cur.fetchone()[0]
        cur.execute("SELECT value FROM index_settings WHERE key='type'")
        row = cur.fetchone()
        index_type = row[0] if row else None
        cur.execute("SELECT value FROM index_settings WHERE key='created_at'")
        row = cur.fetchone()
        created_at = row[0] if row else None
        return {"exists": True, "count": count, "type": index_type, "created_at": created_at}
    except Exception:
        return {"exists": False, "count": 0, "type": None, "created_at": None}
    finally:
        conn.close()
