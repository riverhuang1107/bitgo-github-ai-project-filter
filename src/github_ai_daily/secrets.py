from __future__ import annotations

import os
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod


SERVICE = "github-ai-daily"


class SecretStore(ABC):
    @abstractmethod
    def get(self, name: str) -> str | None: ...

    @abstractmethod
    def set(self, name: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, name: str) -> None: ...


class KeyringStore(SecretStore):
    def __init__(self):
        import keyring

        self.keyring = keyring
        backend = keyring.get_keyring()
        priority = getattr(backend, "priority", 0)
        if priority is None or priority <= 0:
            raise RuntimeError("No usable system keyring is available")

    def get(self, name: str) -> str | None:
        return self.keyring.get_password(SERVICE, name)

    def set(self, name: str, value: str) -> None:
        self.keyring.set_password(SERVICE, name, value)

    def delete(self, name: str) -> None:
        try:
            self.keyring.delete_password(SERVICE, name)
        except self.keyring.errors.PasswordDeleteError:
            pass


class CommandStore(SecretStore):
    def __init__(self, get_cmd: str, put_cmd: str, delete_cmd: str):
        self.get_cmd = _split_command(get_cmd)
        self.put_cmd = _split_command(put_cmd)
        self.delete_cmd = _split_command(delete_cmd)

    def get(self, name: str) -> str | None:
        result = subprocess.run(
            [*self.get_cmd, name], check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            return None
        return result.stdout.rstrip("\r\n")

    def set(self, name: str, value: str) -> None:
        subprocess.run(
            [*self.put_cmd, name], input=value, check=True, text=True, capture_output=True
        )

    def delete(self, name: str) -> None:
        subprocess.run(
            [*self.delete_cmd, name], check=False, text=True, capture_output=True
        )


def get_secret_store() -> SecretStore:
    commands = (
        os.environ.get("GITHUB_AI_SECRET_GET_CMD"),
        os.environ.get("GITHUB_AI_SECRET_PUT_CMD"),
        os.environ.get("GITHUB_AI_SECRET_DELETE_CMD"),
    )
    if all(commands):
        return CommandStore(*commands)
    try:
        return KeyringStore()
    except Exception as exc:
        platform_hint = "Windows Credential Manager" if sys.platform == "win32" else "Secret Service"
        raise RuntimeError(
            f"No secure secret backend available ({platform_hint} unavailable). "
            "On headless Linux configure GITHUB_AI_SECRET_GET_CMD, "
            "GITHUB_AI_SECRET_PUT_CMD and GITHUB_AI_SECRET_DELETE_CMD."
        ) from exc


def _split_command(command: str) -> list[str]:
    if os.name != "nt":
        return shlex.split(command)
    return [part[1:-1] if len(part) >= 2 and part[0] == part[-1] == '"' else part
            for part in shlex.split(command, posix=False)]
