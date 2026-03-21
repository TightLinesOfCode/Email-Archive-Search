import json
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from config import EMAILS_DIR
from fetcher import fetch_and_archive
from indexer import archive_stats, create_index, index_status, search

app = Flask(__name__, template_folder="templates")
app.secret_key = "pop-email-archive"


# ---------------------------------------------------------------------------
# Email list
# ---------------------------------------------------------------------------

@app.route("/")
def email_list():
    emails = []
    if EMAILS_DIR.exists():
        for email_json in EMAILS_DIR.glob("*/email.json"):
            try:
                with open(email_json, encoding="utf-8") as fh:
                    emails.append(json.load(fh))
            except Exception:
                pass
    emails.sort(key=lambda e: e.get("date") or "", reverse=True)
    return render_template("emails.html", emails=emails)


# ---------------------------------------------------------------------------
# Email view
# ---------------------------------------------------------------------------

@app.route("/email/<uid>")
def view_email(uid):
    email_json = EMAILS_DIR / uid / "email.json"
    if not email_json.exists():
        return "Email not found", 404
    with open(email_json, encoding="utf-8") as fh:
        data = json.load(fh)
    return render_template("email.html", email=data)


@app.route("/email/<uid>/body")
def email_body(uid):
    """Serve the HTML body of an email so it can be loaded in an iframe."""
    email_json = EMAILS_DIR / uid / "email.json"
    if not email_json.exists():
        return "", 404
    with open(email_json, encoding="utf-8") as fh:
        data = json.load(fh)
    html = (data.get("body") or {}).get("html") or ""
    return Response(html, mimetype="text/html")


# ---------------------------------------------------------------------------
# Attachment download
# ---------------------------------------------------------------------------

@app.route("/email/<uid>/attachment/<filename>")
def download_attachment(uid, filename):
    safe_name = Path(filename).name  # prevent path traversal
    path = EMAILS_DIR / uid / "attachments" / safe_name
    if not path.exists():
        return "Attachment not found", 404
    return send_file(path, as_attachment=True, download_name=safe_name)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

@app.route("/fetch", methods=["POST"])
def fetch():
    try:
        result = fetch_and_archive()
        flash(
            f"Fetch complete — {result['new']} new, "
            f"{result['skipped']} already archived, "
            f"{result['deleted']} deleted from server.",
            "success",
        )
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


@app.route("/index")
def index_page():
    return redirect(url_for("stats_page"))


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
