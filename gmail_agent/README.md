# Gmail mail tools

These local Python scripts use Gmail IMAP and ask for an explicit confirmation
before changing messages. They do not permanently delete messages.

## Setup

1. Turn on 2-Step Verification for your Google Account, then create an
   **App Password** in Google Account settings under Security. App Passwords
   may be unavailable for some managed accounts or account configurations.
   Use the generated App Password in the script, not your usual Google
   password. Google’s instructions are at
   <https://support.google.com/accounts/answer/185833>.
2. Make sure IMAP access is enabled for Gmail.
3. Run either script from this folder:

   ```sh
   python3 gmail_promotions_cleaner.py
   ```

   Enter your Gmail address and App Password when prompted. The password input
   is hidden and is not saved by the script. Gmail's search count is displayed;
   type `TRASH` to confirm moving the matching messages.

Use `python3 gmail_promotions_cleaner.py --dry-run` to count matching messages
without moving them.

Messages in Trash can generally be recovered for up to 30 days before Gmail
deletes them permanently.

## Label the Primary inbox

Run:

```sh
python3 primary_inbox_labeler.py --dry-run
```

The script asks for the Gmail address and App Password, then previews counts
for the Primary category in Inbox. The “loan details” Finance search is the
exception: it searches across Gmail mail and adds the Finance label wherever
it matches, including archived messages. Gmail search normally excludes Spam
and Trash. Counts can overlap. Message bodies are not printed or saved; Gmail
performs the keyword searches, and the script reads only thread/date metadata
to determine reply status. To apply labels, run without `--dry-run`, review
the counts, and type `LABEL`.

Automatic label rules:

- `Personal`: Primary conversations with at least one message in Sent.
- `Needs Reply`: Primary conversations whose latest Primary message is newer
  than the latest sent message, or that have no sent message.
- `Waiting`: conversations whose latest sent message is at least as recent as
  the latest Primary message.
- `Important`: starred messages, messages matching “important” or “Aditri”,
  or messages from/in Cc/in Bcc for `abhishek10.br@gmail.com` or
  `amrutha3092@gmail.com`.
- `Security`: messages matching “pwd” or “password”.
- `Finance`: messages matching terms such as spent, debit, charged, payment,
  purchase, transaction, or the phrase “loan details” (case-insensitive,
  including “Loan details” and “Loan Details”). Other finance keywords are
  searched in Primary; “loan details” is searched across Gmail mail.
- `Receipts`: messages matching account-credit, deposit, receipt, or order
  confirmation terms.
- `Updates`: messages matching account-update, notification, alert, or
  verification-code terms.
- `Newsletters`: messages matching unsubscribe or email-preferences terms.
- `Work`: messages matching project, meeting, client, deadline, team, or work.

The Work, Finance, Receipts, and Updates rules are keyword-based and may need
manual corrections. When a Primary inbox message matches both financial
searches, `Receipts` takes precedence over `Finance`; the global “loan details”
match still receives Finance. Labels are added without removing existing
labels. `Read Later` is created as an available label but is not automatically
applied because the script cannot reliably infer what you want to read later.
`Personal` means “you replied in this conversation,” following your requested
replacement for `Known`.

Gmail reserves `Important` as a built-in system marker, so the script uses
Gmail's importance marker instead of trying to create a regular label with
that name. This built-in marker may not support a custom color. IMAP can create
and apply the other Gmail labels, but cannot set their display colors. After
applying them, set colors in Gmail on the web: open each regular label's menu
in the left sidebar, choose **Label color**, and use this suggested key:
If a run stops partway through, you can rerun it; applying the same labels
again is safe.

| Label | Suggested color |
|---|---|
| Personal | Blue |
| Needs Reply | Red |
| Waiting | Orange |
| Important | Built-in marker; color may not be customizable |
| Security | Purple |
| Finance | Green |
| Receipts | Teal |
| Work | Dark blue |
| Newsletters | Gray |
| Updates | Light blue |
| Read Later | Yellow |
