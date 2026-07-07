from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import base64
import json
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from github_ai_daily.crypto import (
    WalletAuth,
    build_x_params,
    generate_money_id,
    generate_wallet,
    generate_private_key,
    interface_signature_message,
    load_private_key,
    run_wallet_signer,
    signature_message,
    signed_headers,
    wallet_signed_headers,
)


def test_signature_message_with_query():
    assert (
        signature_message("post", "https://example.test/v1/messages?a=1", "nonce")
        == b"POST\n/v1/messages\n?a=1\nnonce"
    )


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


def test_generate_money_id_is_prefixed_timestamped_and_unique():
    now = datetime(2026, 7, 7, 1, 2, 3, 456789, tzinfo=timezone.utc)

    first = generate_money_id(now)
    second = generate_money_id(now)

    assert first.startswith("money_20260707010203456789_")
    assert second.startswith("money_20260707010203456789_")
    assert first != second
    assert len(first.rsplit("_", 1)[1]) == 12


def test_build_x_params_from_wallet_signer(monkeypatch, tmp_path: Path):
    auth = WalletAuth(
        chain="ltc",
        wallet_address="wallet",
        money="10",
        money_id="20260630001",
        private_key="private",
    )

    def fake_run(command, **kwargs):
        assert "--chain" in command
        assert "ltc" in command
        assert "--private-key" in command
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "wallet_address": "wallet",
                    "money": "10",
                    "money_id": "20260630001",
                    "signature": "signature",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("github_ai_daily.crypto.subprocess.run", fake_run)

    x_params = build_x_params(auth)
    decoded = json.loads(base64.b64decode(x_params).decode("utf-8"))

    assert decoded == {
        "wallet_address": "wallet",
        "money": "10",
        "money_id": "20260630001",
        "signature": "signature",
    }

    path = tmp_path / "interface-key.pem"
    generate_private_key(path)
    key = load_private_key(path)
    headers = wallet_signed_headers(auth, key, nonce="fixed-nonce")
    assert headers["X-Params"] == x_params
    assert headers["X-Nonce"] == "fixed-nonce"
    assert headers["X-Signature"]
    assert headers["X-Public-Key"]

    digest = sha256(interface_signature_message(x_params, "fixed-nonce")).digest()
    key.public_key().verify(
        bytes.fromhex(headers["X-Signature"]),
        digest,
        ec.ECDSA(utils.Prehashed(hashes.SHA256())),
    )


def test_wallet_auth_rejects_missing_private_key():
    auth = WalletAuth(
        chain="ltc",
        wallet_address="wallet",
        money="10",
        money_id="20260630001",
        private_key="",
    )

    try:
        auth.validate()
    except ValueError as exc:
        assert "REASONING_PRIVATE_KEY" in str(exc)
    else:
        raise AssertionError("Expected missing private key to fail")


def test_generate_wallet_from_signer(monkeypatch):
    def fake_run(command, **kwargs):
        assert "--generate-wallet" in command
        assert "--chain" in command
        assert "eth" in command
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "chain": "eth",
                    "wallet_address": "0xwallet",
                    "private_key": "private",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("github_ai_daily.crypto.subprocess.run", fake_run)

    wallet = generate_wallet("eth")

    assert wallet.chain == "eth"
    assert wallet.wallet_address == "0xwallet"
    assert wallet.private_key == "private"


def test_wallet_signer_error_includes_detail(monkeypatch):
    auth = WalletAuth(
        chain="ltc",
        wallet_address="wallet",
        money="10",
        money_id="20260630001",
        private_key="private",
    )
    monkeypatch.setattr(
        "github_ai_daily.crypto.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="unsupported chain"
        ),
    )

    try:
        run_wallet_signer(auth)
    except RuntimeError as exc:
        assert "unsupported chain" in str(exc)
    else:
        raise AssertionError("Expected signer failure")
