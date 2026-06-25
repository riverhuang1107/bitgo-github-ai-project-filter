from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


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
