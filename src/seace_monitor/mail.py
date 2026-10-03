"""Send the daily report by SMTP. Server, account and recipients come from .env."""

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


class MailError(Exception):
    pass


def settings() -> dict:
    missing = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REPORT_TO") if not os.environ.get(k)]
    if missing:
        # The earlier version of this project failed exactly here, silently, every day.
        raise MailError(f"missing in .env: {', '.join(missing)}")
    return {
        "host": os.environ["SMTP_HOST"],
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ["SMTP_USER"],
        "password": os.environ["SMTP_PASSWORD"],
        "sender": os.environ.get("REPORT_FROM") or os.environ["SMTP_USER"],
        "to": [a.strip() for a in os.environ["REPORT_TO"].split(",") if a.strip()],
    }


def message(subject: str, body: str, attachment: Path, sender: str, to: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    msg.add_attachment(attachment.read_bytes(), maintype="text", subtype="csv", filename=attachment.name)
    return msg


def send(subject: str, body: str, attachment: Path) -> list[str]:
    """Send and return the recipients. Raises MailError unless the server accepted every recipient."""
    s = settings()
    msg = message(subject, body, attachment, s["sender"], s["to"])
    try:
        if s["port"] == 465:
            server = smtplib.SMTP_SSL(s["host"], s["port"], timeout=60)
        else:
            server = smtplib.SMTP(s["host"], s["port"], timeout=60)
            server.starttls()
        with server:
            server.login(s["user"], s["password"])
            refused = server.send_message(msg)
    except (smtplib.SMTPException, OSError) as error:
        raise MailError(f"report not sent: {error}") from error
    if refused:
        raise MailError(f"report refused for: {', '.join(refused)}")
    return s["to"]
