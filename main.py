import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))


def _prompt_protocol() -> str:
    """Ask the user which mail protocol to use and return 'IMAP' or 'POP3'."""
    print("Select mail protocol:")
    print("  1) IMAP  — archives all folders")
    print("  2) POP3  — archives inbox only")
    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            return "IMAP"
        if choice == "2":
            return "POP3"
        print("Please enter 1 or 2.")


if __name__ == "__main__":
    protocol = _prompt_protocol()
    os.environ["MAIL_PROTOCOL"] = protocol
    print(f"Using {protocol}.\n")

    from web.app import app

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
