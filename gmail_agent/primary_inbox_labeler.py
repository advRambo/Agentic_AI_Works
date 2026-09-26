from __future__ import annotations

import argparse
import getpass
import imaplib
import re
import sys
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime

from gmail_promotions_cleaner import (
    GmailAuthenticationError,
    batches,
    find_all_mail_folder,
    login_to_gmail,
)


PRIMARY_QUERY = "category:primary in:inbox"
SENT_QUERY = "in:sent"
LOAN_DETAILS_QUERY = '"loan details"'
IMAP_SERVER = "imap.gmail.com"
FETCH_BATCH_SIZE = 100

LABEL_COLORS = {
    "Personal": "blue",
    "Needs Reply": "red",
    "Waiting": "orange",
    "Important": "red",
    "Security": "purple",
    "Finance": "green",
    "Receipts": "teal",
    "Work": "dark blue",
    "Newsletters": "gray",
    "Updates": "light blue",
    "Read Later": "yellow",
}

SEARCH_LABELS = {
    "Important": (
        f'{PRIMARY_QUERY} '
        '{is:starred "important" Aditri '
        'from:abhishek10.br@gmail.com cc:abhishek10.br@gmail.com '
        'bcc:abhishek10.br@gmail.com from:amrutha3092@gmail.com '
        'cc:amrutha3092@gmail.com bcc:amrutha3092@gmail.com}'
    ),
    "Security": f"{PRIMARY_QUERY} {{pwd password}}",
    "Finance": (
        f"{PRIMARY_QUERY} "
        '{spent debit debited charged charge payment paid transaction withdrawal '
        '"loan details"}'
    ),
    "Receipts": (
        f'{PRIMARY_QUERY} '
        '{"account credited" credited deposit deposited receipt "order confirmation"}'
    ),
    "Updates": (
        f'{PRIMARY_QUERY} '
        '{"account update" notification alert "verification code"}'
    ),
    "Newsletters": (
        f'{PRIMARY_QUERY} '
        '{unsubscribe "email preferences" "manage preferences"}'
    ),
    "Work": (
        f"{PRIMARY_QUERY} "
        "{project meeting client deadline team work}"
    ),
}

MESSAGE_METADATA = re.compile(
    rb"\bUID\s+(\d+).*?\bX-GM-THRID\s+(\d+).*?"
    rb'\bINTERNALDATE\s+"([^"]+)"',
    re.DOTALL,
)


def search_uids(mailbox: imaplib.IMAP4_SSL, query: str) -> list[bytes]:
    quoted_query = '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        status, data = mailbox.uid(
            "SEARCH", None, "X-GM-RAW", quoted_query
        )
    except imaplib.IMAP4.error as error:
        raise RuntimeError(
            "Gmail rejected the search command. The IMAP query was safely "
            "quoted; check that IMAP is enabled and retry."
        ) from error
    if status != "OK":
        raise RuntimeError("Gmail search failed.")
    if not data or not data[0]:
        return []
    return data[0].split()


def fetch_thread_dates(
    mailbox: imaplib.IMAP4_SSL, message_uids: list[bytes]
) -> dict[bytes, datetime]:
    thread_dates: dict[bytes, datetime] = {}
    for uid_batch in batches(message_uids, FETCH_BATCH_SIZE):
        uid_set = b",".join(uid_batch).decode("ascii")
        status, data = mailbox.uid(
            "FETCH", uid_set, "(UID X-GM-THRID INTERNALDATE)"
        )
        if status != "OK" or data is None:
            raise RuntimeError("Could not read Gmail message thread metadata.")
        for row in data:
            if not isinstance(row, bytes):
                continue
            match = MESSAGE_METADATA.search(row)
            if not match:
                continue
            thread_id = match.group(2)
            message_date = parsedate_to_datetime(match.group(3).decode("ascii"))
            if message_date.tzinfo is None:
                raise RuntimeError("Gmail returned a message date without a timezone.")
            earliest = datetime.min.replace(tzinfo=message_date.tzinfo)
            if message_date > thread_dates.get(thread_id, earliest):
                thread_dates[thread_id] = message_date
    return thread_dates


def primary_messages_by_thread(
    mailbox: imaplib.IMAP4_SSL, primary_uids: list[bytes]
) -> dict[bytes, list[bytes]]:
    thread_messages: dict[bytes, list[bytes]] = defaultdict(list)
    for uid_batch in batches(primary_uids, FETCH_BATCH_SIZE):
        uid_set = b",".join(uid_batch).decode("ascii")
        status, data = mailbox.uid(
            "FETCH", uid_set, "(UID X-GM-THRID INTERNALDATE)"
        )
        if status != "OK" or data is None:
            raise RuntimeError("Could not read Primary inbox thread metadata.")
        for row in data:
            if not isinstance(row, bytes):
                continue
            match = MESSAGE_METADATA.search(row)
            if match:
                thread_messages[match.group(2)].append(match.group(1))
    return thread_messages


def replied_thread_message_uids(
    mailbox: imaplib.IMAP4_SSL,
    thread_messages: dict[bytes, list[bytes]],
    sent_uids: list[bytes],
) -> tuple[set[bytes], set[bytes], set[bytes]]:
    primary_dates = fetch_thread_dates(
        mailbox, [uid for uids in thread_messages.values() for uid in uids]
    )
    sent_dates = fetch_thread_dates(mailbox, sent_uids)
    replied_threads = set(primary_dates).intersection(sent_dates)
    waiting_threads = {
        thread_id
        for thread_id in replied_threads
        if sent_dates[thread_id] >= primary_dates[thread_id]
    }
    needs_reply_threads = set(primary_dates).difference(waiting_threads)
    personal_uids = {
        uid
        for thread_id in replied_threads
        for uid in thread_messages[thread_id]
    }
    needs_reply_uids = {
        uid
        for thread_id in needs_reply_threads
        for uid in thread_messages[thread_id]
    }
    waiting_uids = {
        uid
        for thread_id in waiting_threads
        for uid in thread_messages[thread_id]
    }
    return personal_uids, needs_reply_uids, waiting_uids


def parse_label_names(listing: list[bytes] | None) -> set[str]:
    names = set()
    for row in listing or []:
        if not row:
            continue
        match = re.search(rb'"((?:[^"\\]|\\.)*)"\s*$', row)
        if match:
            names.add(
                match.group(1)
                .replace(b'\\"', b'"')
                .replace(b"\\\\", b"\\")
                .decode("utf-8")
            )
    return names


def ensure_labels(mailbox: imaplib.IMAP4_SSL, labels: set[str]) -> None:
    status, listing = mailbox.list()
    if status != "OK":
        raise RuntimeError("Could not list existing Gmail labels.")
    existing = parse_label_names(listing)
    for label in sorted(labels - existing):
        if label == "Important":
            continue
        status, _ = mailbox.create(f'"{label}"')
        if status != "OK":
            raise RuntimeError(f"Could not create Gmail label {label!r}.")


def apply_label(
    mailbox: imaplib.IMAP4_SSL, label: str, message_uids: set[bytes]
) -> int:
    applied = 0
    for uid_batch in batches(sorted(message_uids, key=int), FETCH_BATCH_SIZE):
        uid_set = b",".join(uid_batch).decode("ascii")
        imap_label = r"(\Important)" if label == "Important" else f'("{label}")'
        try:
            status, _ = mailbox.uid(
                "STORE", uid_set, "+X-GM-LABELS", imap_label
            )
        except imaplib.IMAP4.error as error:
            raise RuntimeError(
                f"Gmail rejected the {label!r} label update after {applied} "
                "messages in this label had been updated."
            ) from error
        if status != "OK":
            raise RuntimeError(
                f"Failed applying {label!r}; {applied} messages in this label "
                "were updated before the failure."
            )
        applied += len(uid_batch)
    return applied


def collect_label_targets(
    mailbox: imaplib.IMAP4_SSL,
    primary_uids: list[bytes],
    primary_by_thread: dict[bytes, list[bytes]],
) -> dict[str, set[bytes]]:
    targets = {
        label: set(search_uids(mailbox, query))
        for label, query in SEARCH_LABELS.items()
    }
    targets["Personal"], targets["Needs Reply"], targets["Waiting"] = (
        replied_thread_message_uids(
            mailbox,
            primary_by_thread,
            search_uids(mailbox, SENT_QUERY),
        )
    )
    primary_uid_set = set(primary_uids)
    for label, message_uids in targets.items():
        targets[label] = message_uids.intersection(primary_uid_set)
    targets["Finance"].difference_update(targets["Receipts"])
    targets["Finance"].update(search_uids(mailbox, LOAN_DETAILS_QUERY))
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview and apply labels to Gmail's Primary inbox."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show label counts without creating or applying labels.",
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

            primary_uids = search_uids(mailbox, PRIMARY_QUERY)
            if not primary_uids:
                print("No messages found in the Primary inbox.")
                return 0

            primary_by_thread = primary_messages_by_thread(mailbox, primary_uids)
            targets = collect_label_targets(
                mailbox, primary_uids, primary_by_thread
            )
            print(f"Found {len(primary_uids)} messages in the Primary inbox.")
            print("\nLabels to apply (counts can overlap):")
            for label in LABEL_COLORS:
                count = len(targets.get(label, set()))
                note = "" if label in targets else " (suggested; manual choice)"
                print(f"  {label}: {count}{note}")
            print("\nColor suggestions (set in Gmail after labels are created):")
            print("  " + ", ".join(f"{label}={color}" for label, color in LABEL_COLORS.items()))

            if args.dry_run:
                return 0

            confirmation = input(
                "\nType LABEL to create and apply these labels: "
            )
            if confirmation != "LABEL":
                print("No labels were created or applied.")
                return 0

            ensure_labels(mailbox, set(LABEL_COLORS))
            for label in LABEL_COLORS:
                message_uids = targets.get(label, set())
                if message_uids:
                    count = apply_label(mailbox, label, message_uids)
                    print(f"Applied {label!r} to {count} messages.")
            print(
                "Labels were applied. 'Important' uses Gmail's built-in "
                "importance marker; Gmail label colors must be set in Gmail's "
                "web interface."
            )
            return 0
    except GmailAuthenticationError as error:
        print(f"Sign-in failed: {error}", file=sys.stderr)
        return 1
    except (imaplib.IMAP4.error, RuntimeError) as error:
        print(f"Gmail labeling failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
