import base64
from email import message_from_bytes
from pathlib import Path

from github_ai_daily.gmail import parse_recipients, send_report_email


def test_parse_recipients_accepts_secret_style_list():
    assert parse_recipients("a@example.com, b@example.com; c@example.com") == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


def test_gmail_report_message_has_html_and_attachments(monkeypatch, tmp_path: Path):
    html_path = tmp_path / "report.html"
    md_path = tmp_path / "report.md"
    html_path.write_text("<h1>Report</h1>", encoding="utf-8")
    md_path.write_text("# Report", encoding="utf-8")
    captured = {}

    monkeypatch.setenv("MAIL_FROM", "reports@example.com")
    monkeypatch.setattr("github_ai_daily.gmail._load_credentials", lambda: object())
    monkeypatch.setattr(
        "github_ai_daily.gmail._send_raw_message",
        lambda credentials, raw: captured.update({"credentials": credentials, "raw": raw}),
    )

    send_report_email(
        "<h1>Report</h1>",
        ["reader@example.com"],
        "Connectivity",
        [html_path, md_path],
    )

    message = message_from_bytes(base64.urlsafe_b64decode(captured["raw"]))
    assert message["From"] == "reports@example.com"
    assert message["To"] == "reader@example.com"
    assert {part.get_filename() for part in message.walk()} >= {"report.html", "report.md"}
