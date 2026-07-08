from __future__ import annotations

import base64
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BFF_BASE_URL = "https://bitgo.enigmhaven.com"


@dataclass(slots=True)
class BFFTier1Auth:
    chain: str
    wallet_address: str
    private_key: str
    signer_command: str = ""

    def normalized_chain(self) -> str:
        return self.chain.strip().lower()

    def validate(self) -> None:
        if self.normalized_chain() not in {"btc", "eth", "ltc"}:
            raise ValueError("BFF wallet chain must be one of: btc, eth, ltc")
        if not self.wallet_address.strip():
            raise ValueError("BFF wallet address is required")
        if not self.private_key.strip():
            raise ValueError("BFF private key is required")


class BFFClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BFF_BASE_URL,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def get_wallet(self, x_params: str) -> dict[str, Any]:
        return self._get_json("/api/bff/v1/wallet", x_params=x_params)

    def get_transactions(
        self, x_params: str, *, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        return self._get_json(
            "/api/bff/v1/wallet/transactions",
            x_params=x_params,
            params={"page": page, "page_size": page_size},
        )

    def _get_json(
        self,
        path: str,
        *,
        x_params: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.get(path, params=params, headers={"X-Params": x_params})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"BFF response for {path} must be a JSON object")
        return data


def build_tier1_x_params(auth: BFFTier1Auth) -> str:
    signed = run_tier1_signer(auth)
    payload = json.dumps(
        {
            "wallet_address": signed["wallet_address"],
            "signature": signed["signature"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def run_tier1_signer(auth: BFFTier1Auth) -> dict[str, str]:
    auth.validate()
    command, cwd = _signer_command(auth.signer_command)
    completed = subprocess.run(
        [
            *command,
            "--tier1",
            "--chain",
            auth.normalized_chain(),
            "--wallet-address",
            auth.wallet_address,
            "--private-key",
            auth.private_key,
        ],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"BFF wallet signer failed: {detail}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("BFF wallet signer did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("BFF wallet signer JSON root must be an object")
    required = {"wallet_address", "signature"}
    missing = required - set(data)
    if missing:
        raise RuntimeError(
            "BFF wallet signer JSON missing fields: " + ", ".join(sorted(missing))
        )
    return {key: str(data[key]) for key in required}


def _signer_command(configured: str) -> tuple[list[str], Path | None]:
    if configured.strip():
        return shlex.split(configured), None
    repo_root = Path(__file__).resolve().parents[2]
    signer_dir = repo_root / "tools" / "reasoning-signer"
    return ["go", "run", "."], signer_dir
