import json
import shutil
from pathlib import Path


def is_archived(account_dir: Path, folder: str, uid: str) -> bool:
    return (account_dir / folder / uid / "email.json").exists()


def save_email(
    account_dir: Path,
    folder: str,
    uid: str,
    email_dict: dict,
    attachment_files: list[tuple[str, bytes]],
) -> Path:
    """
    Persist an email to disk.

    Layout:
        <account_dir>/<folder>/<uid>/
            email.json
            attachments/
                <filename>
                ...

    Returns the email directory path.
    """
    email_dir = account_dir / folder / uid
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


def delete_archive(account_dir: Path) -> int:
    """
    Delete every archived email under account_dir.
    Returns the number of email directories removed.
    The account_dir itself and any non-email files are left intact.
    """
    count = 0
    if not account_dir.exists():
        return count
    for email_dir in account_dir.glob("*/*/"):
        if (email_dir / "email.json").exists():
            shutil.rmtree(email_dir)
            count += 1
    return count


def delete_email(account_dir: Path, folder: str, uid: str) -> bool:
    """Delete an archived email directory. Returns True if it existed."""
    email_dir = account_dir / folder / uid
    if email_dir.exists():
        shutil.rmtree(email_dir)
        return True
    return False
