import json
import queue
import threading
from datetime import date
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    stream_with_context,
    url_for,
)

from archiver import delete_archive, delete_email
from config import ACCOUNT_DIR, LEAVE_DAYS, LEAVE_ON_SERVER, MAIL_PROTOCOL, READ_ONLY
from fetcher import count_new, fetch_and_archive
from indexer import archive_stats, create_index, delete_from_index, delete_index, index_status, search
from purger import purge_server

app = Flask(__name__, template_folder="templates")
app.secret_key = "pop-email-archive"

PER_PAGE = 50
_VALID_SORT  = {"date", "from", "to", "subject"}
_VALID_ORDER = {"asc", "desc"}

# Maps sanitized IMAP folder names to Gmail-style display names
_FOLDER_LABELS: dict[str, str] = {
    "INBOX":                 "Inbox",
    "Gmail_Sent_Mail":       "Sent",
    "Gmail_Drafts":          "Drafts",
    "Gmail_Spam":            "Spam",
    "Gmail_Trash":           "Trash",
    "Gmail_Chats":           "Chats",
    "Google_Mail_Sent_Mail": "Sent",
    "Google_Mail_Drafts":    "Drafts",
    "Google_Mail_Spam":      "Spam",
    "Google_Mail_Trash":     "Trash",
}


# ---------------------------------------------------------------------------
# Email list
# ---------------------------------------------------------------------------

@app.route("/")
def email_list():
    folder_filter = request.args.get("folder", "")
    sort_by = request.args.get("sort", "date")
    order   = request.args.get("order", "desc")
    if sort_by not in _VALID_SORT:
        sort_by = "date"
    if order not in _VALID_ORDER:
        order = "desc"
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    emails = []
    all_folders_set: set[str] = set()
    if ACCOUNT_DIR.exists():
        for email_json in ACCOUNT_DIR.glob("*/*/email.json"):
            try:
                with open(email_json, encoding="utf-8") as fh:
                    data = json.load(fh)
                folder = data.get("folder") or email_json.parent.parent.name
                if folder:
                    all_folders_set.add(folder)
                if not folder_filter or folder == folder_filter:
                    emails.append(data)
            except Exception:
                pass

    def _sort_key(e):
        if sort_by == "from":
            f = e.get("from") or {}
            return (f.get("name") or f.get("address") or "").lower()
        if sort_by == "to":
            to_list = e.get("to") or []
            first = to_list[0] if to_list else {}
            return (first.get("name") or first.get("address") or "").lower()
        if sort_by == "subject":
            return (e.get("subject") or "").lower()
        return e.get("date") or ""

    emails.sort(key=_sort_key, reverse=(order == "desc"))

    all_folders = sorted(all_folders_set)

    total       = len(emails)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page        = min(page, total_pages)
    start       = (page - 1) * PER_PAGE
    page_emails = emails[start:start + PER_PAGE]

    folder_label = (
        _FOLDER_LABELS.get(folder_filter, folder_filter) if folder_filter else "All Mail"
    )

    return render_template(
        "emails.html",
        emails=page_emails,
        all_folders=all_folders,
        active_folder=folder_filter,
        folder_label=folder_label,
        sort_by=sort_by,
        order=order,
        page=page,
        total_pages=total_pages,
        total=total,
    )


# ---------------------------------------------------------------------------
# Delete emails
# ---------------------------------------------------------------------------

@app.route("/emails/delete", methods=["POST"])
def delete_emails():
    selected = request.form.getlist("sel")   # each value is "folder/uid"
    folder_filter = request.form.get("folder", "")
    sort_by       = request.form.get("sort", "date")
    order         = request.form.get("order", "desc")
    page          = request.form.get("page", "1")

    deleted = 0
    index_entries: list[tuple[str, str]] = []
    for item in selected:
        folder, _, uid = item.partition("/")
        if folder and uid:
            if delete_email(ACCOUNT_DIR, folder, uid):
                deleted += 1
                index_entries.append((folder, uid))

    if index_entries:
        delete_from_index(index_entries)

    if deleted:
        flash(f"Deleted {deleted} email{'s' if deleted != 1 else ''}.", "success")

    return redirect(url_for(
        "email_list", folder=folder_filter, sort=sort_by, order=order, page=page
    ))


# ---------------------------------------------------------------------------
# Email view
# ---------------------------------------------------------------------------

@app.route("/email/<folder>/<uid>")
def view_email(folder, uid):
    email_json = ACCOUNT_DIR / folder / uid / "email.json"
    if not email_json.exists():
        return "Email not found", 404
    with open(email_json, encoding="utf-8") as fh:
        data = json.load(fh)
    return render_template("email.html", email=data)


@app.route("/email/<folder>/<uid>/body")
def email_body(folder, uid):
    """Serve the HTML body of an email so it can be loaded in an iframe."""
    email_json = ACCOUNT_DIR / folder / uid / "email.json"
    if not email_json.exists():
        return "", 404
    with open(email_json, encoding="utf-8") as fh:
        data = json.load(fh)
    html = (data.get("body") or {}).get("html") or ""
    return Response(html, mimetype="text/html")


# ---------------------------------------------------------------------------
# Attachment download
# ---------------------------------------------------------------------------

@app.route("/email/<folder>/<uid>/attachment/<path:filename>")
def download_attachment(folder, uid, filename):
    safe_name = Path(filename).name  # prevent path traversal
    path = ACCOUNT_DIR / folder / uid / "attachments" / safe_name
    if not path.exists():
        return "Attachment not found", 404
    return send_file(path, as_attachment=True, download_name=safe_name)


# ---------------------------------------------------------------------------
# Fetch preview + fetch
# ---------------------------------------------------------------------------

def _estimate_time(count: int) -> str:
    """Return a human-readable time estimate for fetching `count` emails."""
    if count == 0:
        return "instant — nothing to download"
    secs = count * 2          # ~2 seconds per email is a reasonable middle estimate
    if secs < 10:
        return "a few seconds"
    if secs < 90:
        return f"about {secs} seconds"
    mins = round(secs / 60)
    return f"about {mins} minute{'s' if mins != 1 else ''}"


@app.route("/fetch/preview")
def fetch_preview():
    try:
        info = count_new()
    except Exception as e:
        flash(f"Could not connect to mail server: {e}", "error")
        return redirect(url_for("email_list"))

    will_fetch = info["new"]
    if info["fetch_limit"] is not None:
        will_fetch = min(will_fetch, info["fetch_limit"])

    return render_template(
        "fetch_preview.html",
        info=info,
        will_fetch=will_fetch,
        estimate=_estimate_time(will_fetch),
    )


@app.route("/fetch/stream")
def fetch_stream():
    """Stream fetch progress as Server-Sent Events."""
    q: queue.Queue = queue.Queue()
    result_box: dict = {}

    def run_fetch():
        def on_progress(n, folder, uid, subject):
            q.put({"n": n, "folder": folder, "subject": subject or ""})
        try:
            result_box["result"] = fetch_and_archive(on_progress=on_progress)
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            q.put(None)  # sentinel

    threading.Thread(target=run_fetch, daemon=True).start()

    def generate():
        while True:
            item = q.get()
            if item is None:
                if "error" in result_box:
                    payload = json.dumps({"error": result_box["error"]})
                else:
                    r = result_box.get("result", {})
                    payload = json.dumps({
                        "done":    True,
                        "new":     r.get("new", 0),
                        "skipped": r.get("skipped", 0),
                        "errors":  r.get("errors", []),
                    })
                yield f"data: {payload}\n\n"
                break
            yield f"data: {json.dumps(item)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/fetch", methods=["POST"])
def fetch():
    try:
        result = fetch_and_archive()
        parts = [
            f"Fetch complete ({result['protocol']}) —",
            f"{result['new']} new across {result['folders_scanned']} folder(s),",
            f"{result['skipped']} already archived.",
        ]
        if result.get("deleted"):
            parts.append(f"{result['deleted']} deleted from server.")
        if result.get("read_only"):
            parts.append("(read-only: server unchanged)")
        flash(" ".join(parts), "success")
        for err in result["errors"]:
            flash(err, "error")
    except Exception as e:
        flash(f"Fetch failed: {e}", "error")
    return redirect(url_for("email_list"))


# ---------------------------------------------------------------------------
# Stats & index management
# ---------------------------------------------------------------------------

@app.route("/stats", methods=["GET", "POST"])
def stats_page():
    stats = archive_stats()
    status = index_status()
    result = None
    if request.method == "POST":
        comprehensive = request.form.get("type") == "comprehensive"
        result = create_index(comprehensive=comprehensive)
        status = index_status()
    return render_template("stats.html", stats=stats, status=status, result=result)


@app.route("/index/delete", methods=["POST"])
def delete_index_route():
    delete_index()
    flash("Search index deleted.", "success")
    return redirect(url_for("stats_page"))


@app.route("/index")
def index_page():
    return redirect(url_for("stats_page"))


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

@app.route("/admin")
def admin_page():
    stats = archive_stats()
    return render_template(
        "admin.html",
        stats=stats,
        mail_protocol=MAIL_PROTOCOL,
        read_only=READ_ONLY,
        leave_on_server=LEAVE_ON_SERVER,
        leave_days=LEAVE_DAYS,
    )


@app.route("/admin/delete-archive", methods=["POST"])
def delete_archive_route():
    confirmation = request.form.get("confirmation", "").strip()
    if confirmation != "DELETE ALL":
        flash("Confirmation text did not match. Archive was not deleted.", "error")
        return redirect(url_for("admin_page"))
    count = delete_archive(ACCOUNT_DIR)
    delete_index()
    flash(f"Archive deleted — {count} email{'s' if count != 1 else ''} removed.", "success")
    return redirect(url_for("admin_page"))


# ---------------------------------------------------------------------------
# Purge Server
# ---------------------------------------------------------------------------

def _parse_date_param(name: str) -> date | None:
    raw = request.args.get(name, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@app.route("/admin/purge")
def purge_preview():
    if MAIL_PROTOCOL != "IMAP" or READ_ONLY:
        flash("Purge Server is only available when using IMAP with READ_ONLY disabled.", "error")
        return redirect(url_for("admin_page"))
    date_from = _parse_date_param("date_from")
    date_to   = _parse_date_param("date_to")
    return render_template(
        "purge_server.html",
        date_from=str(date_from) if date_from else "",
        date_to=str(date_to)   if date_to   else "",
        leave_on_server=LEAVE_ON_SERVER,
        leave_days=LEAVE_DAYS,
    )


@app.route("/admin/purge/stream")
def purge_stream():
    """Stream purge progress as Server-Sent Events."""
    if MAIL_PROTOCOL != "IMAP" or READ_ONLY:
        return Response(
            'data: {"error": "Purge not available"}\n\n',
            mimetype="text/event-stream",
        )

    date_from = _parse_date_param("date_from")
    date_to   = _parse_date_param("date_to")

    q: queue.Queue = queue.Queue()
    result_box: dict = {}

    def run_purge():
        def on_progress(n, folder, uid, _subject):
            q.put({"n": n, "folder": folder, "uid": uid})
        try:
            result_box["result"] = purge_server(
                date_from=date_from,
                date_to=date_to,
                on_progress=on_progress,
            )
        except Exception as e:
            result_box["error"] = str(e)
        finally:
            q.put(None)

    threading.Thread(target=run_purge, daemon=True).start()

    def generate():
        while True:
            item = q.get()
            if item is None:
                if "error" in result_box:
                    payload = json.dumps({"error": result_box["error"]})
                else:
                    r = result_box.get("result", {})
                    payload = json.dumps({
                        "done":     True,
                        "deleted":  r.get("deleted", 0),
                        "skipped":  r.get("skipped", 0),
                        "errors":   r.get("errors", []),
                    })
                yield f"data: {payload}\n\n"
                break
            yield f"data: {json.dumps(item)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.route("/search")
def search_page():
    query = request.args.get("q", "").strip()
    results = []
    error = None
    if query:
        try:
            results = search(query)
        except Exception as e:
            error = str(e)
    status = index_status()
    return render_template(
        "search.html", query=query, results=results, error=error, status=status
    )
