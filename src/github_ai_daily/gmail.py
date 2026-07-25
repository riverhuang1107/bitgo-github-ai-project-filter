from __future__ import annotations

import base64
import json
import os
import re
from email.message import EmailMessage
from pathlib import Path
from typing import Any


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_CREDENTIALS_FILE = Path("secrets/gmail_credentials.json")
DEFAULT_TOKEN_FILE = Path("secrets/gmail_token.json")


def parse_recipients(value: str) -> list[str]:
    return [item for item in re.split(r"[\s,;]+", value.strip()) if item]


def authorize_gmail(force: bool = False, console: bool = False) -> Path:
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    token_path = _token_path()
    if token_path.exists() and not force:
        return token_path
    flow = _load_installed_app_flow()
    if console:
        flow.redirect_uri = "http://localhost"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("Open this URL in a browser and authorize Gmail sending:")
        print(auth_url)
        redirected_url = input("Paste the full redirected URL here: ").strip()
        flow.fetch_token(authorization_response=redirected_url)
    else:
        flow.run_local_server(port=8080, host="localhost", open_browser=True)
    _save_token(flow.credentials, token_path)
    return token_path


def send_report_email(
    html: str, recipients: list[str], subject: str, attachments: list[Path]
) -> None:
    if not recipients:
        raise ValueError("At least one Gmail recipient is required")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ.get("MAIL_FROM") or "me"
    message["To"] = ", ".join(recipients)
    message.set_content("请使用支持 HTML 的邮件客户端查看 Bitgo 模型连通性报告。")
    message.add_alternative(html, subtype="html")
    for path in attachments:
        message.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    _send_raw_message(_load_credentials(), raw)


def _send_raw_message(credentials: Any, raw: str) -> None:
    from google.auth.transport.requests import AuthorizedSession

    response = AuthorizedSession(credentials).post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        json={"raw": raw},
        timeout=60,
    )
    response.raise_for_status()


def _load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_info = _load_token_info()
    credentials = (
        Credentials.from_authorized_user_info(token_info, scopes=[GMAIL_SEND_SCOPE])
        if token_info
        else None
    )
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        if not os.environ.get("GMAIL_TOKEN_JSON"):
            _save_token(credentials, _token_path())
    if not credentials or not credentials.valid:
        raise RuntimeError(
            "Gmail OAuth token is missing or invalid. Run `github-ai-daily gmail-auth`."
        )
    return credentials


def _load_installed_app_flow():
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow.from_client_config(
        _load_credentials_info(), scopes=[GMAIL_SEND_SCOPE]
    )


def _load_credentials_info() -> dict[str, Any]:
    raw = os.environ.get("GMAIL_CREDENTIALS_JSON")
    if raw:
        return json.loads(raw)
    path = Path(os.environ.get("GMAIL_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_FILE))
    if not path.exists():
        raise RuntimeError(
            f"Missing Gmail OAuth client file: {path}. "
            "Download an OAuth desktop client JSON from Google Cloud Console."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_token_info() -> dict[str, Any] | None:
    raw = os.environ.get("GMAIL_TOKEN_JSON")
    if raw:
        return json.loads(raw)
    path = _token_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _save_token(credentials: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")


def _token_path() -> Path:
    return Path(os.environ.get("GMAIL_TOKEN_FILE", DEFAULT_TOKEN_FILE))
