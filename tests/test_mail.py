"""Mail sending with a fake SMTP server; nothing leaves the machine."""

import smtplib
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from seace_monitor import mail
from seace_monitor.report import pending
from seace_monitor.search import LIMA
from seace_monitor.store import mark_reported

ENV = {"SMTP_HOST": "smtp.example.org", "SMTP_PORT": "587", "SMTP_USER": "monitor@example.org",
       "SMTP_PASSWORD": "secret", "REPORT_TO": "a@example.org, b@example.org"}


class FakeSMTP:
    sent = []
    refuse = {}
    fail_login = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.tls = host, port, False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    def send_message(self, msg):
        FakeSMTP.sent.append((self, msg))
        return FakeSMTP.refuse

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def smtp(monkeypatch, tmp_path):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("REPORT_FROM", raising=False)
    FakeSMTP.sent, FakeSMTP.refuse, FakeSMTP.fail_login = [], {}, False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    csv_file = tmp_path / "2026-10-03.csv"
    csv_file.write_text("nid_proceso;nomenclatura\n1;LP-ABR-1\n", encoding="utf-8-sig")
    return csv_file


def test_report_goes_to_every_recipient_with_the_csv(smtp):
    assert mail.send("Informe SEACE", "cuerpo", [smtp]) == ["a@example.org", "b@example.org"]
    server, msg = FakeSMTP.sent[0]
    assert server.tls
    assert msg["From"] == "monitor@example.org"
    assert msg["To"] == "a@example.org, b@example.org"
    attachment = next(msg.iter_attachments())
    assert attachment.get_filename() == "2026-10-03.csv"


def test_phone_page_goes_as_html(smtp, tmp_path):
    page = tmp_path / "obras-abiertas-2026-10-03.html"
    page.write_text("<!doctype html><p>obras</p>", encoding="utf-8")
    mail.send("Informe SEACE", "cuerpo", [smtp, page])
    _, msg = FakeSMTP.sent[0]
    assert [a.get_content_type() for a in msg.iter_attachments()] == ["text/csv", "text/html"]


def test_missing_setting_is_an_error_not_a_silent_skip(smtp, monkeypatch):
    monkeypatch.delenv("SMTP_PASSWORD")
    with pytest.raises(mail.MailError, match="SMTP_PASSWORD"):
        mail.send("Informe SEACE", "cuerpo", [smtp])


def test_rejected_login_is_an_error(smtp):
    FakeSMTP.fail_login = True
    with pytest.raises(mail.MailError, match="not sent"):
        mail.send("Informe SEACE", "cuerpo", [smtp])


def test_a_refused_recipient_is_an_error(smtp):
    FakeSMTP.refuse = {"b@example.org": (550, b"no such user")}
    with pytest.raises(mail.MailError, match="b@example.org"):
        mail.send("Informe SEACE", "cuerpo", [smtp])


def test_marked_obras_leave_the_next_report(conn):
    now = datetime(2026, 10, 3, 9, 0, tzinfo=LIMA)
    conn.execute(
        """INSERT INTO licitaciones (nid_proceso, nomenclatura, entidad, objeto, descripcion, departamentos, fecha_limite_ofertas)
           VALUES (1, 'LP-ABR-1', 'MD', 'Obra', 'OBRA', '{LA LIBERTAD}', %s)""", [now + timedelta(days=3)])
    assert [i["nid_proceso"] for i in pending(conn, ["LA LIBERTAD"], Path("data"), now)] == [1]
    mark_reported(conn, [1])
    assert pending(conn, ["LA LIBERTAD"], Path("data"), now) == []
