# POP Email Archive Search

Search and archive Gmail messages via POP3. Runs in Docker or directly on your machine.

---

## Gmail Setup

### 1. Enable POP access in Gmail

1. Open Gmail and go to **Settings** (gear icon) → **See all settings**
2. Select the **Forwarding and POP/IMAP** tab
3. Under **POP Download**, select **Enable POP for all mail**
4. Click **Save Changes**

### 2. Create an App Password

Gmail requires an App Password instead of your normal account password for third-party POP3 access.

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - You must have 2-Step Verification enabled on your account
2. Choose **Mail** as the app and **Other** as the device (name it anything, e.g. "POP Archive")
3. Copy the generated 16-character password

---

## Configuration

1. Copy the example env file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your Gmail credentials:

   ```
   EMAIL_ADDRESS=you@gmail.com
   EMAIL_PASSWORD=your_16_char_app_password
   ```

   The POP3 and SMTP settings are pre-configured for Gmail and do not need to change.

3. Review the other settings in `.env` — port, archive directory, retention days, and optional date range filters are all documented inline.

---

## Running in Docker (recommended)

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)

### Start the container

```bash
docker compose up --build
```

Then open **http://localhost:5000** in your browser.

To run in the background:

```bash
docker compose up --build -d
```

To stop:

```bash
docker compose down
```

### How the archive directory works

Docker cannot access your filesystem directly. It mounts a folder from your machine into the container at a fixed path:

```
Your machine                       Docker container
─────────────────────────────────────────────────────
$LOCAL_MACHINE_ARCHIVE_DIR          ←mount→     /pop-email-archive
```

Set `LOCAL_MACHINE_ARCHIVE_DIR` in `.env` to control where emails are stored on your machine:

```bash
# Default — a folder inside the repo (gitignored)
LOCAL_MACHINE_ARCHIVE_DIR=./pop-email-archive

# Absolute path — external drive or NAS
LOCAL_MACHINE_ARCHIVE_DIR=/Volumes/MyDrive/EmailArchive
LOCAL_MACHINE_ARCHIVE_DIR=/mnt/nas/email
```

The folder is created automatically if it does not exist. Files persist after the container stops.

---

## Running Locally (without Docker)

### Prerequisites
- Python 3.12+

### Install dependencies

```bash
pip install -r requirements.txt
```

### Set the archive directory

When running locally, emails are written to the path set in `DATA_DIR` (defaults to `/pop-email-archive`). Override it in `.env` to a local path:

```bash
DATA_DIR=./pop-email-archive
```

### Start the web server

```bash
PYTHONPATH=src python main.py
```

Then open **http://localhost:5000** in your browser.

To use a different port, set `PORT` in `.env` or prefix the command:

```bash
PORT=8080 PYTHONPATH=src python main.py
```

---

## Web Interface

| Page | URL | Description |
|---|---|---|
| Inbox | `/` | Browse all archived emails |
| Email view | `/email/<id>` | Read an email, view and download attachments |
| Search | `/search` | Full-text search across the index |
| Stats & Index | `/stats` | Archive heuristics, build or rebuild the search index |

Use the **Fetch Emails** button in the nav bar to pull new messages from Gmail at any time.

---

## Project Structure

```
.
├── pop-email-archive/      # Archive directory (gitignored, mounted into Docker)
├── main.py                 # Entry point — starts the web server
├── src/
│   ├── config.py           # Loads settings from .env
│   ├── fetcher.py          # POP3 fetch & archive logic
│   ├── email_parser.py     # Parses raw RFC-822 messages into JSON
│   ├── archiver.py         # Writes email.json and attachments to disk
│   ├── pop_client.py       # Low-level POP3 connection helpers
│   ├── indexer.py          # SQLite FTS5 search index
│   └── web/
│       ├── app.py          # Flask routes
│       └── templates/      # HTML templates
├── .env                    # Your credentials (gitignored — never commit this)
├── .env.example            # Credential template (safe to commit)
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```
