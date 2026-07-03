from __future__ import annotations

import base64
import hashlib
import json
import secrets
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

SUPPORTED_WALLET_CHAINS = {"ltc", "btc", "eth"}


@dataclass(slots=True)
class WalletAuth:
    chain: str
    wallet_address: str
    money: str
    money_id: str
    private_key: str
    signer_command: str = ""

    def normalized_chain(self) -> str:
        return self.chain.strip().lower()

    def validate(self) -> None:
        chain = self.normalized_chain()
        if chain not in SUPPORTED_WALLET_CHAINS:
            raise ValueError("reasoning wallet chain must be one of: btc, eth, ltc")
        if not self.wallet_address.strip():
            raise ValueError("reasoning wallet address is required")
        if not str(self.money).strip():
            raise ValueError("reasoning money is required")
        if not str(self.money_id).strip():
            raise ValueError("reasoning money_id is required")
        if not self.private_key.strip():
            raise ValueError("REASONING_PRIVATE_KEY is required")


@dataclass(slots=True)
class GeneratedWallet:
    chain: str
    wallet_address: str
    private_key: str


def generate_private_key(path: Path, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Private key already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_private_key(path: Path) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise TypeError("Configured key is not an ECDSA private key")
    return key


def public_key_hex(key: ec.EllipticCurvePrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return der.hex()


def signature_message(method: str, url: str, nonce: str) -> bytes:
    parsed = urlsplit(url)
    parts = [method.upper(), parsed.path or "/"]
    if parsed.query:
        parts.append(f"?{parsed.query}")
    parts.append(nonce)
    return "\n".join(parts).encode("utf-8")


def signed_headers(
    method: str, url: str, key: ec.EllipticCurvePrivateKey, nonce: str | None = None
) -> dict[str, str]:
    nonce = nonce or secrets.token_hex(16)
    message = signature_message(method, url, nonce)
    digest = hashlib.sha256(message).digest()
    signature = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    return {
        "Content-Type": "application/json",
        "X-Nonce": nonce,
        "X-Signature": signature.hex(),
        "X-Public-Key": public_key_hex(key),
    }


def interface_signature_message(x_params: str, nonce: str) -> bytes:
    return f"{x_params}{nonce}".encode("utf-8")


def interface_signed_headers(
    x_params: str, key: ec.EllipticCurvePrivateKey, nonce: str | None = None
) -> dict[str, str]:
    nonce = nonce or secrets.token_hex(16)
    digest = hashlib.sha256(interface_signature_message(x_params, nonce)).digest()
    signature = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    return {
        "X-Nonce": nonce,
        "X-Signature": signature.hex(),
        "X-Public-Key": public_key_hex(key),
    }


def wallet_signed_headers(
    auth: WalletAuth, key: ec.EllipticCurvePrivateKey, nonce: str | None = None
) -> dict[str, str]:
    x_params = build_x_params(auth)
    return {
        "Content-Type": "application/json",
        "X-Params": x_params,
        **interface_signed_headers(x_params, key, nonce),
    }


def build_x_params(auth: WalletAuth) -> str:
    signed = run_wallet_signer(auth)
    header_params = {
        "wallet_address": signed["wallet_address"],
        "money": signed["money"],
        "money_id": signed["money_id"],
        "signature": signed["signature"],
    }
    payload = json.dumps(
        header_params, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def generate_wallet(chain: str, signer_command: str = "") -> GeneratedWallet:
    normalized = chain.strip().lower()
    if normalized not in SUPPORTED_WALLET_CHAINS:
        raise ValueError("reasoning wallet chain must be one of: btc, eth, ltc")
    command, cwd = _signer_command(signer_command)
    completed = subprocess.run(
        [*command, "--generate-wallet", "--chain", normalized],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"reasoning wallet generation failed: {detail}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "reasoning wallet generator did not return valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("reasoning wallet generator JSON root must be an object")
    required = {"chain", "wallet_address", "private_key"}
    missing = required - set(data)
    if missing:
        raise RuntimeError(
            "reasoning wallet generator JSON missing fields: "
            + ", ".join(sorted(missing))
        )
    return GeneratedWallet(
        chain=str(data["chain"]),
        wallet_address=str(data["wallet_address"]),
        private_key=str(data["private_key"]),
    )


def run_wallet_signer(auth: WalletAuth) -> dict[str, str]:
    auth.validate()
    command, cwd = _signer_command(auth.signer_command)
    command = [
        *command,
        "--chain",
        auth.normalized_chain(),
        "--wallet-address",
        auth.wallet_address,
        "--money",
        str(auth.money),
        "--money-id",
        str(auth.money_id),
        "--private-key",
        auth.private_key,
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"reasoning wallet signer failed: {detail}")
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("reasoning wallet signer did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise RuntimeError("reasoning wallet signer JSON root must be an object")
    required = {"wallet_address", "money", "money_id", "signature"}
    missing = required - set(data)
    if missing:
        raise RuntimeError(
            "reasoning wallet signer JSON missing fields: " + ", ".join(sorted(missing))
        )
    signature = data.get("signature")
    if not isinstance(signature, str) or not signature:
        raise RuntimeError("reasoning wallet signer returned an empty signature")
    return {key: str(data[key]) for key in required}


def _signer_command(configured: str) -> tuple[list[str], Path | None]:
    if configured.strip():
        return shlex.split(configured), None
    repo_root = Path(__file__).resolve().parents[2]
    signer_dir = repo_root / "tools" / "reasoning-signer"
    return ["go", "run", "."], signer_dir
