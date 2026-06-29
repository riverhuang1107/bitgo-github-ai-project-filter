from pathlib import Path

from github_ai_daily.config import DEFAULT_MAIL_FROM, Settings
from github_ai_daily.mail import (
    SMTP_KEY,
    SMTP_KEY_ID,
    create_message,
    provision_mail,
    remove_mail,
    send_message,
)
from github_ai_daily.secrets import SecretStore


class MemoryStore(SecretStore):
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


def test_mime_message_contains_html_and_attachment(tmp_path: Path):
    attachment = tmp_path / "report.md"
    attachment.write_text("# Report", encoding="utf-8")
    message = create_message(
        Settings().mail_from,
        "reader@example.com",
        "Daily",
        "<h1>Daily</h1>",
        [attachment],
    )
    assert message.is_multipart()
    assert message["From"] == DEFAULT_MAIL_FROM
    assert message.get_body(preferencelist=("html",)).get_content().strip() == "<h1>Daily</h1>"
    assert any(part.get_filename() == "report.md" for part in message.iter_attachments())


def test_resend_provisioning_rotates_after_success(monkeypatch):
    deleted = []

    class FakeProvisioner:
        def __init__(self, management_key):
            assert management_key == "management"

        def create_sending_key(self, name):
            return "new-id", "new-token"

        def delete_key(self, key_id):
            deleted.append(key_id)

        def close(self):
            pass

    monkeypatch.setattr("github_ai_daily.mail.ResendProvisioner", FakeProvisioner)
    store = MemoryStore()
    store.set(SMTP_KEY, "old-token")
    store.set(SMTP_KEY_ID, "old-id")
    provision_mail(Settings(), store, "management", verify=False)
    assert store.get(SMTP_KEY) == "new-token"
    assert store.get(SMTP_KEY_ID) == "new-id"
    assert deleted == ["old-id"]


def test_auto_backend_uses_agent_mail_when_available(monkeypatch, tmp_path: Path):
    commands = []

    class Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(command, **kwargs):
        commands.append(command)
        if command == ["agently-cli", "+me"]:
            return Result('{"ok": true, "data": {}}')
        if "--confirmation-token" in command:
            return Result('{"ok": true, "data": {"queued": true}}')
        return Result(
            '{"ok": true, "data": {"confirmation_required": true, '
            '"confirmation_token": "ctk_test"}}'
        )

    attachment = tmp_path / "report.html"
    attachment.write_text("<h1>Report</h1>", encoding="utf-8")
    message = create_message(
        Settings().mail_from,
        "reader@example.com",
        "Daily",
        "<h1>Daily</h1>",
        [attachment],
    )

    monkeypatch.setattr("github_ai_daily.mail.shutil.which", lambda name: "/usr/bin/agently-cli")
    monkeypatch.setattr("github_ai_daily.mail.subprocess.run", fake_run)

    send_message(Settings(mail_backend="auto"), MemoryStore(), message)

    assert commands[0] == ["agently-cli", "+me"]
    assert commands[1][:3] == ["agently-cli", "message", "+send"]
    assert "--body-file" in commands[1]
    assert "--attachment" in commands[1]
    assert commands[2][-2:] == ["--confirmation-token", "ctk_test"]


def test_resend_backend_uses_smtp_secret(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def ehlo(self):
            pass

        def starttls(self, context):
            sent["tls"] = True

        def login(self, username, password):
            sent["username"] = username
            sent["password"] = password

        def send_message(self, message):
            sent["to"] = message["To"]

    store = MemoryStore()
    store.set(SMTP_KEY, "smtp-token")
    message = create_message(
        Settings().mail_from,
        "reader@example.com",
        "Daily",
        "<h1>Daily</h1>",
    )
    monkeypatch.setattr("github_ai_daily.mail.smtplib.SMTP", FakeSMTP)

    send_message(Settings(mail_backend="resend"), store, message)

    assert sent == {
        "host": "smtp.resend.com",
        "port": 587,
        "timeout": 30,
        "tls": True,
        "username": "resend",
        "password": "smtp-token",
        "to": "reader@example.com",
    }


def test_remove_requires_management_key_for_remote_credential():
    store = MemoryStore()
    store.set(SMTP_KEY_ID, "remote-id")
    try:
        remove_mail(store, None)
    except RuntimeError as exc:
        assert "RESEND_MANAGEMENT_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected remove_mail to require a management key")
