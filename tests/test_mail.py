from pathlib import Path

from github_ai_daily.config import Settings
from github_ai_daily.mail import (
    SMTP_KEY,
    SMTP_KEY_ID,
    create_message,
    provision_mail,
    remove_mail,
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
        "AI Daily <daily@example.com>",
        "reader@example.com",
        "Daily",
        "<h1>Daily</h1>",
        [attachment],
    )
    assert message.is_multipart()
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


def test_remove_requires_management_key_for_remote_credential():
    store = MemoryStore()
    store.set(SMTP_KEY_ID, "remote-id")
    try:
        remove_mail(store, None)
    except RuntimeError as exc:
        assert "RESEND_MANAGEMENT_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected remove_mail to require a management key")
