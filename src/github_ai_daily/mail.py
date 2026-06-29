from __future__ import annotations

import json
import os
import shutil
import smtplib
import ssl
import subprocess
import tempfile
from email.message import EmailMessage
from pathlib import Path

import httpx

from .config import Settings
from .secrets import SecretStore


SMTP_KEY = "resend-smtp-key"
SMTP_KEY_ID = "resend-smtp-key-id"
RESEND_API = "https://api.resend.com"


def create_message(
    sender: str,
    recipient: str,
    subject: str,
    html_body: str,
    attachments: list[Path] | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content("请使用支持 HTML 的邮件客户端查看 GitHub AI 日报。")
    msg.add_alternative(html_body, subtype="html")
    for path in attachments or []:
        subtype = "html" if path.suffix.lower() == ".html" else "markdown"
        msg.add_attachment(
            path.read_bytes(),
            maintype="text",
            subtype=subtype,
            filename=path.name,
        )
    return msg


def send_message(settings: Settings, store: SecretStore, message: EmailMessage) -> None:
    backend = resolve_mail_backend(settings)
    if backend == "agent":
        send_agent_message(message)
        return
    if backend != "resend":
        raise RuntimeError(f"Unsupported mail backend: {backend}")
    send_smtp_message(settings, store, message)


def resolve_mail_backend(settings: Settings) -> str:
    backend = os.environ.get("GITHUB_AI_MAIL_BACKEND") or settings.mail_backend
    backend = backend.strip().lower()
    if backend in {"resend", "smtp"}:
        return "resend"
    if backend == "agent":
        if not agent_mail_available():
            raise RuntimeError("Agent Mail CLI is not available or not authorized")
        return "agent"
    if backend == "auto":
        return "agent" if agent_mail_available() else "resend"
    raise RuntimeError("mail.backend must be one of: auto, agent, resend")


def agent_mail_available() -> bool:
    if not shutil.which("agently-cli"):
        return False
    result = subprocess.run(
        ["agently-cli", "+me"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        data = _json_from_output(result.stdout)
    except RuntimeError:
        return False
    return bool(data.get("ok"))


def send_agent_message(message: EmailMessage) -> None:
    body = message.get_body(preferencelist=("html", "plain"))
    if body is None:
        raise RuntimeError("Email message has no body")
    with tempfile.TemporaryDirectory(prefix=".github-ai-daily-mail-", dir=Path.cwd()) as tmp:
        tmp_path = Path(tmp)
        body_path = tmp_path / ("body.html" if body.get_content_subtype() == "html" else "body.txt")
        body_path.write_text(body.get_content(), encoding="utf-8")
        attachments = _write_agent_attachments(message, tmp_path)
        command = [
            "agently-cli",
            "message",
            "+send",
            "--to",
            str(message["To"]),
            "--subject",
            str(message["Subject"]),
            "--body-file",
            _relative_to_cwd(body_path),
        ]
        for attachment in attachments:
            command.extend(["--attachment", _relative_to_cwd(attachment)])
        first = _run_agent_command(command)
        token = first.get("data", {}).get("confirmation_token")
        if first.get("data", {}).get("confirmation_required") and token:
            _run_agent_command([*command, "--confirmation-token", str(token)])


def _write_agent_attachments(message: EmailMessage, directory: Path) -> list[Path]:
    paths = []
    for index, part in enumerate(message.iter_attachments(), start=1):
        filename = part.get_filename() or f"attachment-{index}"
        path = directory / Path(filename).name
        path.write_bytes(part.get_payload(decode=True) or b"")
        paths.append(path)
    return paths


def _run_agent_command(command: list[str]) -> dict:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Agent Mail send failed: {detail}")
    return _json_from_output(result.stdout)


def _json_from_output(output: str) -> dict:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"Command did not return JSON: {output.strip()}")
    data = json.loads(output[start : end + 1])
    if not isinstance(data, dict):
        raise RuntimeError("Command returned non-object JSON")
    if not data.get("ok"):
        raise RuntimeError(f"Command failed: {data}")
    return data


def _relative_to_cwd(path: Path) -> str:
    return str(path.resolve().relative_to(Path.cwd().resolve()))


def send_smtp_message(settings: Settings, store: SecretStore, message: EmailMessage) -> None:
    password = store.get(SMTP_KEY)
    if not password:
        raise RuntimeError("SMTP credential is not initialized; run `github-ai-daily init`")
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(settings.smtp_username, password)
        smtp.send_message(message)


class ResendProvisioner:
    def __init__(self, management_key: str, timeout: float = 30):
        self.client = httpx.Client(
            base_url=RESEND_API,
            headers={"Authorization": f"Bearer {management_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    def create_sending_key(self, name: str) -> tuple[str, str]:
        response = self.client.post(
            "/api-keys", json={"name": name[:50], "permission": "sending_access"}
        )
        response.raise_for_status()
        data = response.json()
        return str(data["id"]), str(data["token"])

    def delete_key(self, key_id: str) -> None:
        response = self.client.delete(f"/api-keys/{key_id}")
        if response.status_code not in {200, 204, 404}:
            response.raise_for_status()

    def close(self) -> None:
        self.client.close()


def provision_mail(
    settings: Settings,
    store: SecretStore,
    management_key: str,
    verify: bool = True,
) -> None:
    provisioner = ResendProvisioner(management_key)
    old_id = store.get(SMTP_KEY_ID)
    old_token = store.get(SMTP_KEY)
    new_id = new_token = ""
    try:
        new_id, new_token = provisioner.create_sending_key("github-ai-daily")
        store.set(SMTP_KEY, new_token)
        store.set(SMTP_KEY_ID, new_id)
        if verify:
            message = create_message(
                settings.mail_from,
                settings.mail_test_to,
                "GitHub AI Daily SMTP 初始化成功",
                "<p>Resend SMTP 凭据已创建并验证成功。</p>",
            )
            send_message(settings, store, message)
        if old_id and old_id != new_id:
            provisioner.delete_key(old_id)
    except Exception:
        if new_id:
            try:
                provisioner.delete_key(new_id)
            except Exception:
                pass
        if old_token:
            store.set(SMTP_KEY, old_token)
        else:
            store.delete(SMTP_KEY)
        if old_id:
            store.set(SMTP_KEY_ID, old_id)
        else:
            store.delete(SMTP_KEY_ID)
        raise
    finally:
        provisioner.close()


def remove_mail(store: SecretStore, management_key: str | None) -> None:
    key_id = store.get(SMTP_KEY_ID)
    if key_id and not management_key:
        raise RuntimeError(
            "RESEND_MANAGEMENT_API_KEY must be injected to revoke the remote SMTP credential"
        )
    if key_id:
        provisioner = ResendProvisioner(management_key)
        try:
            provisioner.delete_key(key_id)
        finally:
            provisioner.close()
    store.delete(SMTP_KEY)
    store.delete(SMTP_KEY_ID)


def management_key_from_env() -> str:
    key = os.environ.pop("RESEND_MANAGEMENT_API_KEY", "")
    if not key:
        raise RuntimeError("RESEND_MANAGEMENT_API_KEY must be injected for this operation")
    return key
