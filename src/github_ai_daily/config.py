from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import tomllib


DEFAULT_ENDPOINT = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
DEFAULT_MODEL = "claude-4.6-opus"
DEFAULT_MAIL_ADDRESS = "hhq4326@agent.qq.com"
DEFAULT_MAIL_DISPLAY_NAME = "Agent Mail"
DEFAULT_MAIL_FROM = f"{DEFAULT_MAIL_DISPLAY_NAME} <{DEFAULT_MAIL_ADDRESS}>"


def user_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "github-ai-daily"


@dataclass(slots=True)
class Settings:
    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL
    private_key_path: str = ""
    wallet_chain: str = ""
    wallet_address: str = ""
    money: str = ""
    money_id: str = ""
    signer_command: str = ""
    output_dir: str = "output"
    mail_from: str = DEFAULT_MAIL_FROM
    mail_test_to: str = ""
    mail_backend: str = "auto"
    smtp_host: str = "smtp.resend.com"
    smtp_port: int = 587
    smtp_username: str = "resend"

    @classmethod
    def load(cls, path: Path) -> "Settings":
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        app = data.get("app", {})
        reasoning = data.get("reasoning", {})
        mail = data.get("mail", {})
        return cls(
            endpoint=reasoning.get("endpoint", DEFAULT_ENDPOINT),
            model=reasoning.get("model", DEFAULT_MODEL),
            private_key_path=reasoning.get("private_key_path", ""),
            wallet_chain=reasoning.get("wallet_chain", ""),
            wallet_address=reasoning.get("wallet_address", ""),
            money=str(reasoning.get("money", "")),
            money_id=str(reasoning.get("money_id", "")),
            signer_command=reasoning.get("signer_command", ""),
            output_dir=app.get("output_dir", "output"),
            mail_from=mail.get("from") or DEFAULT_MAIL_FROM,
            mail_test_to=mail.get("test_to", ""),
            mail_backend=mail.get("backend", "auto"),
            smtp_host=mail.get("host", "smtp.resend.com"),
            smtp_port=int(mail.get("port", 587)),
            smtp_username=mail.get("username", "resend"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (
            "[app]\n"
            f'output_dir = "{_escape(self.output_dir)}"\n\n'
            "[reasoning]\n"
            f'endpoint = "{_escape(self.endpoint)}"\n'
            f'model = "{_escape(self.model)}"\n'
            f'private_key_path = "{_escape(self.private_key_path)}"\n\n'
            f'wallet_chain = "{_escape(self.wallet_chain)}"\n'
            f'wallet_address = "{_escape(self.wallet_address)}"\n'
            f'money = "{_escape(self.money)}"\n'
            f'money_id = "{_escape(self.money_id)}"\n'
            f'signer_command = "{_escape(self.signer_command)}"\n\n'
            "[mail]\n"
            f'from = "{_escape(self.mail_from)}"\n'
            f'test_to = "{_escape(self.mail_test_to)}"\n'
            f'backend = "{_escape(self.mail_backend)}"\n'
            f'host = "{_escape(self.smtp_host)}"\n'
            f"port = {self.smtp_port}\n"
            f'username = "{_escape(self.smtp_username)}"\n'
        )
        path.write_text(text, encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def default_config_path() -> Path:
    return user_config_dir() / "config.toml"
