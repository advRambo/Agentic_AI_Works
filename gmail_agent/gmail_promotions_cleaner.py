from __future__ import annotations

import argparse
import getpass
import imaplib
import re
import sys
from collections.abc import Iterator


PROMOTIONS_QUERY = "category:promotions"
IMAP_SERVER = "imap.gmail.com"
STORE_BATCH_SIZE = 100


class GmailAuthenticationError(RuntimeError):
    pass


def login_to_gmail(
    mailbox: imaplib.IMAP4_SSL, email_address: str, app_password: str
) -> None:
    try:
        mailbox.login(email_address, app_password)
    except imaplib.IMAP4.error as error:
        response = str(error)
        if "application-specific password required" in response.lower():
            raise GmailAuthenticationError(
                "Google requires an App Password for this account. Enable "
                "2-Step Verification, create an App Password in your Google "
                "Account's Security settings, then enter that 16-character "
                "password here instead of your usual Google password. If "
                "App Passwords are unavailable, your account configuration "
                "may not support IMAP App Password sign-in."
            ) from error
        raise GmailAuthenticationError(
            "Gmail rejected the IMAP sign-in. Check the Gmail address and "
            "make sure you entered a current Google App Password, not your "
            "usual Google password."
        ) from error


def find_all_mail_folder(mailbox: imaplib.IMAP4_SSL) -> str:
    status, folders = mailbox.list()
    if status != "OK" or folders is None:
        raise RuntimeError("Could not list Gmail folders.")

    for folder in folders:
        if not folder or not re.search(rb"\(.*\\All(?:\s|\))", folder):
            continue
        match = re.search(rb'"((?:[^"\\]|\\.)*)"\s*$', folder)
        if match:
            return match.group(1).replace(b'\\"', b'"').replace(b"\\\\", b"\\").decode(
                "ascii"
            )
        name = folder.rsplit(b" ", 1)[-1].strip(b'"')
        try:
            return name.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Could not decode Gmail's All Mail folder name.") from error

    raise RuntimeError(
        "Gmail did not report an All Mail folder. Check that IMAP access is "
        "enabled for this account."
    )


def find_promotions_messages(mailbox: imaplib.IMAP4_SSL) -> list[bytes]:
    status, data = mailbox.uid(
        "SEARCH", None, "X-GM-RAW", f'"{PROMOTIONS_QUERY}"'
    )
    if status != "OK":
        raise RuntimeError("Gmail could not search for Promotions messages.")
    if not data or not data[0]:
        return []
    return data[0].split()


def batches(items: list[bytes], size: int) -> Iterator[list[bytes]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def move_messages_to_trash(
    mailbox: imaplib.IMAP4_SSL, message_uids: list[bytes]
) -> int:
    moved = 0
    for batch in batches(message_uids, STORE_BATCH_SIZE):
        uid_set = b",".join(batch).decode("ascii")
        status, _ = mailbox.uid(
            "STORE", uid_set, "+X-GM-LABELS", r"(\Trash)"
        )
        if status != "OK":
            raise RuntimeError(
                f"Gmail failed to move a batch of {len(batch)} messages to Trash. "
                f"{moved} messages were moved before the failure."
            )
        moved += len(batch)
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move Gmail messages in the Promotions category to Trash."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count matching messages without moving them to Trash.",
    )
    args = parser.parse_args()

    email_address = input("Gmail address: ").strip()
    app_password = getpass.getpass("Google App Password (input hidden): ").replace(
        " ", ""
    )
    if not email_address or not app_password:
        parser.error("Both a Gmail address and App Password are required.")

    try:
        with imaplib.IMAP4_SSL(IMAP_SERVER) as mailbox:
            login_to_gmail(mailbox, email_address, app_password)
            all_mail_folder = find_all_mail_folder(mailbox)
            status, _ = mailbox.select(f'"{all_mail_folder}"')
            if status != "OK":
                raise RuntimeError("Could not open Gmail's All Mail folder.")

            message_uids = find_promotions_messages(mailbox)
            print(f"Found {len(message_uids)} messages matching {PROMOTIONS_QUERY!r}.")

            if not message_uids or args.dry_run:
                return 0

            confirmation = input(
                "Type TRASH to move all of these messages to Gmail Trash: "
            )
            if confirmation != "TRASH":
                print("No messages were moved.")
                return 0

            moved = move_messages_to_trash(mailbox, message_uids)
            print(f"Moved {moved} messages to Trash.")
            return 0
    except GmailAuthenticationError as error:
        print(f"Sign-in failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
