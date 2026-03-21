import json
from pathlib import Path


def is_archived(emails_dir: Path, uid: str) -> bool:
    return (emails_dir / uid / "email.json").exists()


def save_email(
    emails_dir: Path,
    uid: str,
    email_dict: dict,
    attachment_files: list[tuple[str, bytes]],
) -> Path:
    """
    Persist an email to disk.

    Layout:
        <emails_dir>/<uid>/
            email.json
            attachments/
                <filename>
                ...

    Returns the email directory path.
    """
    email_dir = emails_dir / uid
    email_dir.mkdir(parents=True, exist_ok=True)

    json_path = email_dir / "email.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(email_dict, fh, indent=2, ensure_ascii=False)

    if attachment_files:
        attachments_dir = email_dir / "attachments"
        attachments_dir.mkdir(exist_ok=True)
        for filename, content in attachment_files:
            safe_name = Path(filename).name  # strip any directory component
            (attachments_dir / safe_name).write_bytes(content)

    return email_dir
