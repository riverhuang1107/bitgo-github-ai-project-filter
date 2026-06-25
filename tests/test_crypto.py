from hashlib import sha256
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from github_ai_daily.crypto import (
    generate_private_key,
    load_private_key,
    signature_message,
    signed_headers,
)


def test_signature_message_with_query():
    assert signature_message(
        "post", "https://example.test/v1/messages?a=1", "nonce"
    ) == b"POST\n/v1/messages\n?a=1\nnonce"


def test_generated_signature_verifies_prehashed(tmp_path: Path):
    path = tmp_path / "key.pem"
    generate_private_key(path)
    key = load_private_key(path)
    url = "https://example.test/v1/messages"
    headers = signed_headers("POST", url, key, nonce="fixed")
    digest = sha256(signature_message("POST", url, "fixed")).digest()
    key.public_key().verify(
        bytes.fromhex(headers["X-Signature"]),
        digest,
        ec.ECDSA(utils.Prehashed(hashes.SHA256())),
    )
    assert bytes.fromhex(headers["X-Public-Key"]).startswith(b"0")

