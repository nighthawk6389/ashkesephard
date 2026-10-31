"""Reading the bot's inbox over IMAP, turning raw messages into IncomingEmail, and replying over SMTP."""
import email
import email.policy
import email.utils
import imaplib
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage

from bs4 import BeautifulSoup

PROCESSED_FOLDER = "Processed-by-bot"
IGNORED_FOLDER = "Ignored-by-bot"
MAX_IMAGES = 12
MAX_DOCUMENTS = 2
MIN_IMAGE_BYTES = 6_000  # smaller images are signature logos and tracking pixels


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class IncomingEmail:
    uid: str
    message_id: str
    sender: str
    sender_display: str
    subject: str
    date: datetime
    text: str
    quoted: str
    in_reply_to: list = field(default_factory=list)
    images: list = field(default_factory=list)
    documents: list = field(default_factory=list)


# ---------------------------------------------------------------- parsing

QUOTE_MARKERS = [
    re.compile(r"^On .{0,200}?wrote:\s*$", re.M | re.S),          # Gmail / Apple Mail
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.M | re.I),  # Outlook
    re.compile(r"^_{10,}\s*$\n^From:", re.M),                     # Outlook web
    re.compile(r"^From: .+\n(?:Sent|Date): ", re.M),
]
SIGNOFFS = re.compile(r"^(?:Sent from my (?:iPhone|iPad|Android|Galaxy).*|Get Outlook for \w+.*)$", re.M | re.I)


def split_quoted(text):
    """Separate what the sender wrote from the conversation it quotes."""
    text = text.replace("\r\n", "\n")
    cut = len(text)
    for rx in QUOTE_MARKERS:
        m = rx.search(text)
        if m and m.start() < cut:
            cut = m.start()
    own, quoted = text[:cut], text[cut:]
    own_lines = []
    for line in own.split("\n"):
        if line.startswith(">"):
            quoted += "\n" + line
        else:
            own_lines.append(line)
    own = SIGNOFFS.sub("", "\n".join(own_lines))
    return re.sub(r"\n{3,}", "\n\n", own).strip(), quoted.strip()


def html_to_text(markup):
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(["style", "script", "head"]):
        tag.decompose()
    for quote in soup.select("blockquote, .gmail_quote"):
        quote.insert_before("\nOn earlier message wrote:\n")  # lets split_quoted cut here
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4"]):
        block.insert_after("\n")
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", soup.get_text()).strip()


def parse_message(uid, raw):
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    display, address = email.utils.parseaddr(str(msg.get("From", "")))
    try:
        date = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        date = date if date.tzinfo else date.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        date = datetime.now(timezone.utc)

    plain, markup, images, documents = None, None, [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        disposition = part.get_content_disposition()
        if ctype.startswith("image/") or ctype == "application/pdf" or (
                ctype == "application/octet-stream" and re.search(r"\.(jpe?g|png|heic|heif|webp|gif|pdf)$", part.get_filename() or "", re.I)):
            data = part.get_payload(decode=True) or b""
            name = part.get_filename() or f"attachment-{len(images) + len(documents) + 1}"
            if name.lower().endswith(".pdf") or ctype == "application/pdf":
                if len(documents) < MAX_DOCUMENTS:
                    documents.append(Attachment(name, "application/pdf", data))
            elif len(data) >= MIN_IMAGE_BYTES and len(images) < MAX_IMAGES:
                images.append(Attachment(name, ctype, data))
            continue
        if disposition == "attachment":
            continue
        if ctype == "text/plain" and plain is None:
            plain = part.get_content()
        elif ctype == "text/html" and markup is None:
            markup = part.get_content()

    body = plain if plain and plain.strip() else html_to_text(markup or "")
    text, quoted = split_quoted(body)
    references = " ".join(str(msg.get(h, "")) for h in ("In-Reply-To", "References"))
    return IncomingEmail(
        uid=uid,
        message_id=str(msg.get("Message-ID", "")).strip() or f"<no-id-{uid}@local>",
        sender=address.lower(),
        sender_display=display,
        subject=str(msg.get("Subject", "")).strip(),
        date=date,
        text=text[:20_000],
        quoted=quoted[:4_000],
        in_reply_to=re.findall(r"<[^>]+>", references),
        images=images,
        documents=documents,
    )


# ---------------------------------------------------------------- IMAP

class Mailbox:
    def __init__(self, settings, ssl_context=None):
        self.settings = settings
        self.ssl_context = ssl_context or ssl.create_default_context()
        self.imap = None

    def __enter__(self):
        self.imap = imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port, ssl_context=self.ssl_context)
        self.imap.login(self.settings.bot_address, self.settings.app_password)
        for folder in (PROCESSED_FOLDER, IGNORED_FOLDER):
            self.imap.create(folder)  # answers NO when it already exists; that's fine
        self._check(self.imap.select("INBOX"), "select INBOX")
        return self

    def __exit__(self, *exc):
        try:
            self.imap.expunge()
            self.imap.close()
        finally:
            self.imap.logout()

    @staticmethod
    def _check(result, what):
        status, data = result
        if status != "OK":
            raise RuntimeError(f"IMAP {what} failed: {data}")
        return data

    def count(self):
        data = self._check(self.imap.uid("SEARCH", None, "ALL"), "search")
        return len(data[0].split()) if data and data[0] else 0

    def fetch(self, limit):
        """Oldest messages first; BODY.PEEK leaves them unread for anyone watching the inbox."""
        data = self._check(self.imap.uid("SEARCH", None, "ALL"), "search")
        uids = data[0].split() if data and data[0] else []
        for uid in uids[:limit]:
            parts = self._check(self.imap.uid("FETCH", uid, "(BODY.PEEK[])"), f"fetch {uid!r}")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw:
                yield uid.decode(), raw

    def move(self, uid, folder):
        self._check(self.imap.uid("COPY", uid, folder), f"copy {uid} to {folder}")
        self._check(self.imap.uid("STORE", uid, "+FLAGS", r"(\Deleted)"), f"delete {uid}")


# ---------------------------------------------------------------- SMTP

def build_reply(settings, incoming, body, cc=None):
    reply = EmailMessage()
    reply["From"] = email.utils.formataddr(("AshkeSephard Recipe Bot", settings.bot_address))
    reply["To"] = email.utils.formataddr((incoming.sender_display, incoming.sender))
    if cc:
        reply["Cc"] = ", ".join(cc)
    subject = incoming.subject or "Your recipe email"
    reply["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    reply["In-Reply-To"] = incoming.message_id
    reply["References"] = " ".join(incoming.in_reply_to + [incoming.message_id])
    reply["Message-ID"] = email.utils.make_msgid(domain=settings.bot_address.split("@")[-1] or "localhost")
    reply["Date"] = email.utils.formatdate(localtime=True)
    reply.set_content(body)
    return reply


def send_all(settings, messages, ssl_context=None):
    if not messages:
        return
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                          context=ssl_context or ssl.create_default_context()) as smtp:
        smtp.login(settings.bot_address, settings.app_password)
        for message in messages:
            smtp.send_message(message)
