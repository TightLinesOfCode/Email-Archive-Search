# Email Archive Search

Archive and search your Gmail messages locally. Supports both **IMAP** (all folders) and **POP3** (inbox only). Runs in Docker or directly on your machine.

---

## Quick Start

1. [Set up Gmail access](#gmail-setup) (enable IMAP or POP3, create an App Password)
2. [Configure your `.env` file](#configuration)
3. [Run with Docker](#running-in-docker-recommended) or [locally](#running-locally-without-docker)
4. Use the terminal menu to fetch emails or switch to the web UI

---

## Gmail Setup

### 1. Enable IMAP or POP3 access

Go to Gmail **Settings** → **See all settings** → **Forwarding and POP/IMAP** tab.

- **IMAP** (recommended) — archives all folders (Inbox, Sent, Drafts, etc.)
  - Under *IMAP access*, select **Enable IMAP**
- **POP3** — archives inbox only
  - Under *POP Download*, select **Enable POP for all mail**

Click **Save Changes**.

### 2. Create an App Password

Gmail requires an App Password (not your regular password) for third-party access.

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - Requires 2-Step Verification to be enabled on your account
2. Name it anything (e.g. "Email Archive") and click **Create**
3. Copy the generated 16-character password — you'll need it in the next step

---

## Configuration

1. Copy the example env file:

   ```bash
   cp .env-example .env
   ```

2. Open `.env` and fill in your Gmail credentials:

   ```
   EMAIL_ADDRESS=you@gmail.com
   EMAIL_PASSWORD=your_16_char_app_password
   ```

3. Set your protocol (defaults to IMAP if not set via env; you'll be prompted at startup):

   ```
   MAIL_PROTOCOL=IMAP    # or POP3
   ```

4. Review the other settings — archive directory, fetch limits, date filters, and read-only mode are all documented inline in `.env-example`.

**Key settings at a glance:**

| Setting | Default | Description |
|---|---|---|
| `MAIL_PROTOCOL` | `IMAP` | `IMAP` (all folders) or `POP3` (inbox only) |
| `FETCH_LIMIT` | `10` | Max emails per fetch run (`ALL` for no limit) |
| `FETCH_DATE_FROM` / `TO` | _(blank)_ | Only fetch emails in this date range (YYYY-MM-DD) |
| `READ_ONLY` | `true` | Fetch without modifying anything on the server |
| `DATA_DIR` | `pop-email-archive` | Where archived emails are stored on disk |
| `PORT` | `5000` | Web UI port |

---

## Running in Docker (recommended)

**Prerequisites:** [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

```bash
# Start (builds automatically)
docker compose up --build

# Start in the background
docker compose up --build -d

# Stop
docker compose down
```

Then open **http://localhost:5000**.

### Archive directory in Docker

Docker mounts a folder from your machine into the container:

```
Your machine                      Docker container
────────────────────────────────────────────────────
$LOCAL_MACHINE_ARCHIVE_DIR  →mount→  /pop-email-archive
```

Set `LOCAL_MACHINE_ARCHIVE_DIR` in `.env` to control where emails land on your machine:

```bash
LOCAL_MACHINE_ARCHIVE_DIR=./pop-email-archive   # default — folder inside the repo
LOCAL_MACHINE_ARCHIVE_DIR=/Volumes/MyDrive/Email # external drive
LOCAL_MACHINE_ARCHIVE_DIR=/mnt/nas/email         # NAS
```

The folder is created automatically if it doesn't exist and persists after the container stops.

---

## Running Locally (without Docker)

**Prerequisites:** Python 3.12+

```bash
pip install -r requirements.txt
```

Set `DATA_DIR` in `.env` to a local path (the default `/pop-email-archive` is an absolute path):

```bash
DATA_DIR=./pop-email-archive
```

Start the application:

```bash
PYTHONPATH=src python main.py
```

This opens an interactive terminal menu:

```
  1) Fetch        — download new emails into the local archive
  2) Purge        — delete archived emails from the IMAP server
  3) Both         — fetch first, then purge
  4) Switch to Web App
  5) Exit
```

Select **Switch to Web App** to start the web server, then open **http://localhost:5000**.

### Command-line arguments

Pass an operation and options directly to skip the interactive menu:

```bash
PYTHONPATH=src python main.py <operation> [options]
```

| Argument | Description |
|---|---|
| `fetch` \| `purge` \| `both` \| `web` | Operation to run (omit for interactive menu) |
| `--protocol IMAP\|POP3`, `-p` | Mail protocol (overrides `MAIL_PROTOCOL` env var) |
| `--date-from YYYY-MM-DD` | Fetch emails on or after this date |
| `--date-to YYYY-MM-DD` | Fetch emails on or before this date |
| `--limit N\|ALL` | Max emails to fetch (overrides `FETCH_LIMIT`) |
| `--delay SECS` | Seconds between fetched emails (overrides `FETCH_DELAY`) |
| `--purge-from YYYY-MM-DD` | Purge emails on or after this date |
| `--purge-to YYYY-MM-DD` | Purge emails on or before this date |
| `--port PORT` | Web app port (overrides `PORT`, default `5000`) |
| `--yes`, `-y` | Skip all confirmation prompts |

**Examples:**

```bash
# Fetch all emails from 2024 without prompts
PYTHONPATH=src python main.py fetch --protocol IMAP --date-from 2024-01-01 --date-to 2024-12-31 --limit ALL --yes

# Purge archived emails from a specific range
PYTHONPATH=src python main.py purge --purge-from 2023-01-01 --purge-to 2023-12-31 --yes

# Start the web app on a custom port
PYTHONPATH=src python main.py web --port 8080
```

---

## CLI (headless, no web server)

`fetch_cli.py` is a standalone headless tool for fetch/purge without the menu or web app:

```bash
PYTHONPATH=src python fetch_cli.py          # interactive prompts
PYTHONPATH=src python fetch_cli.py fetch    # fetch only
PYTHONPATH=src python fetch_cli.py purge    # purge only (requires IMAP + READ_ONLY=false)
PYTHONPATH=src python fetch_cli.py both     # fetch then purge
```

The CLI shows a full configuration summary before running and asks for confirmation.

---

## Web Interface

| Page | URL | Description |
|---|---|---|
| Inbox | `/` | Browse all archived emails, filter by folder, sort by date/sender/subject |
| Email view | `/email/<folder>/<id>` | Read an email, view and download attachments |
| Search | `/search` | Full-text search across the archive |
| Stats | `/stats` | Archive statistics and search index management |
| Admin | `/admin` | Delete archive data or purge emails from the IMAP server |

Use the **Fetch Emails** button in the nav bar to pull new messages from your mail server at any time.

> **Purge** permanently deletes emails from your IMAP server that are already in your local archive. It requires `MAIL_PROTOCOL=IMAP` and `READ_ONLY=false`. You will be asked to confirm twice.

---

## Project Structure

```
.
├── main.py                 # Primary entry point — terminal menu + CLI args
├── fetch_cli.py            # Headless CLI for fetch / purge without the web app
├── src/
│   ├── config.py           # Loads all settings from .env
│   ├── fetcher.py          # IMAP/POP3 fetch and archive logic
│   ├── archiver.py         # Writes email.json and attachments to disk
│   ├── imap_client.py      # Low-level IMAP connection helpers
│   ├── pop_client.py       # Low-level POP3 connection helpers
│   ├── indexer.py          # SQLite FTS5 search index
│   ├── purger.py           # Deletes archived emails from the IMAP server
│   └── web/
│       ├── app.py          # Flask routes
│       └── templates/      # HTML templates
├── pop-email-archive/      # Archive directory (gitignored, mounted into Docker)
├── .env                    # Your credentials (gitignored — never commit this)
├── .env-example            # Template with all settings documented
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```
