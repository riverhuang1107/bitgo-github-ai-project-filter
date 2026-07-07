from argparse import Namespace
from types import SimpleNamespace

from github_ai_daily.cli import cmd_init, reasoning_auth
from github_ai_daily.config import DEFAULT_MAIL_FROM, Settings, WalletProfile


def test_init_does_not_require_mail_from(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.delenv("GITHUB_AI_MAIL_FROM", raising=False)
    monkeypatch.setenv("GITHUB_AI_MAIL_TEST_TO", "reader@example.com")
    monkeypatch.setattr("github_ai_daily.cli.generate_private_key", lambda path: None)
    monkeypatch.setattr("github_ai_daily.cli.get_secret_store", lambda: object())
    monkeypatch.setattr(
        "github_ai_daily.cli.management_key_from_env", lambda: "management"
    )
    monkeypatch.setattr(
        "github_ai_daily.cli.provision_mail",
        lambda settings, store, management_key, verify: captured.update(
            {
                "mail_from": settings.mail_from,
                "mail_test_to": settings.mail_test_to,
                "management_key": management_key,
                "verify": verify,
            }
        ),
    )
    settings = Settings(output_dir=str(tmp_path / "output"))
    args = Namespace(
        config=tmp_path / "config.toml", no_git=True, skip_mail_verification=True
    )

    assert cmd_init(args, settings) == 0

    assert captured == {
        "mail_from": DEFAULT_MAIL_FROM,
        "mail_test_to": "reader@example.com",
        "management_key": "management",
        "verify": False,
    }


def test_init_still_requires_mail_test_to(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_AI_MAIL_TEST_TO", raising=False)
    monkeypatch.setattr("github_ai_daily.cli.generate_private_key", lambda path: None)
    settings = Settings(output_dir=str(tmp_path / "output"))
    args = Namespace(
        config=tmp_path / "config.toml", no_git=True, skip_mail_verification=True
    )

    try:
        cmd_init(args, settings)
    except RuntimeError as exc:
        assert "GITHUB_AI_MAIL_TEST_TO" in str(exc)
    else:
        raise AssertionError("Expected init to require GITHUB_AI_MAIL_TEST_TO")


def test_reasoning_auth_uses_cli_over_env(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "env-private")
    monkeypatch.setenv("REASONING_WALLET_CHAIN", "btc")
    settings = Settings(
        wallet_chain="ltc",
        wallet_address="settings-wallet",
        money="10",
        money_id="settings-id",
    )
    args = Namespace(
        private_key="cli-private",
        chain="eth",
        wallet_address="cli-wallet",
        money="20",
        money_id="cli-id",
        signer_command="custom-signer",
    )

    auth = reasoning_auth(settings, args)

    assert auth.private_key == "cli-private"
    assert auth.chain == "eth"
    assert auth.wallet_address == "cli-wallet"
    assert auth.money == "20"
    assert auth.money_id == "cli-id"
    assert auth.signer_command == "custom-signer"


def test_reasoning_auth_uses_matching_wallet_profile(monkeypatch):
    monkeypatch.delenv("REASONING_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("REASONING_ETH_PRIVATE_KEY", "eth-private")
    settings = Settings(
        wallet_chain="ltc",
        wallet_address="ltc-wallet",
        money="10",
        money_id="ltc-id",
        wallets={
            "eth": WalletProfile(
                wallet_address="0xwallet",
                money="20",
                money_id="eth-id",
                signer_command="eth-signer",
            )
        },
    )
    args = Namespace(
        private_key=None,
        chain="eth",
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
    )

    auth = reasoning_auth(settings, args)

    assert auth.chain == "eth"
    assert auth.wallet_address == "0xwallet"
    assert auth.money == "20"
    assert auth.money_id == "eth-id"
    assert auth.private_key == "eth-private"
    assert auth.signer_command == "eth-signer"


def test_reasoning_auth_generates_money_id_when_missing(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    monkeypatch.setattr(
        "github_ai_daily.cli.generate_money_id", lambda: "money_generated"
    )
    settings = Settings(
        wallet_chain="ltc",
        wallet_address="wallet",
        money="10",
    )
    args = Namespace(
        private_key=None,
        chain=None,
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
    )

    auth = reasoning_auth(settings, args)

    assert auth.money_id == "money_generated"


def test_reasoning_auth_does_not_reuse_mismatched_legacy_wallet(monkeypatch):
    monkeypatch.setenv("REASONING_ETH_PRIVATE_KEY", "eth-private")
    settings = Settings(
        wallet_chain="ltc",
        wallet_address="ltc-wallet",
        money="10",
        money_id="ltc-id",
    )
    args = Namespace(
        private_key=None,
        chain="eth",
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
    )

    try:
        reasoning_auth(settings, args)
    except ValueError as exc:
        assert "reasoning wallet address is required" in str(exc)
    else:
        raise AssertionError("Expected explicit ETH chain to require an ETH wallet")


def test_reasoning_auth_generates_new_wallet_when_requested(monkeypatch):
    monkeypatch.delenv("REASONING_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(
        "github_ai_daily.cli.generate_money_id", lambda: "money_generated"
    )
    captured = {}

    def fake_generate_wallet(chain, signer_command):
        captured["chain"] = chain
        captured["signer_command"] = signer_command
        return SimpleNamespace(
            chain=chain,
            wallet_address="0xnew",
            private_key="new-private",
        )

    monkeypatch.setattr("github_ai_daily.cli.generate_wallet", fake_generate_wallet)
    settings = Settings(
        wallet_chain="eth",
        wallet_address="0xold",
        money="10",
        money_id="old-id",
        signer_command="custom-signer",
    )
    args = Namespace(
        private_key=None,
        chain="eth",
        wallet_address=None,
        money="20",
        money_id=None,
        signer_command=None,
        new_wallet=True,
    )

    auth = reasoning_auth(settings, args)

    assert captured == {"chain": "eth", "signer_command": "custom-signer"}
    assert auth.chain == "eth"
    assert auth.wallet_address == "0xnew"
    assert auth.private_key == "new-private"
    assert auth.money == "20"
    assert auth.money_id == "money_generated"


def test_reasoning_auth_requires_private_key(monkeypatch):
    monkeypatch.delenv("REASONING_PRIVATE_KEY", raising=False)
    settings = Settings(
        wallet_chain="ltc", wallet_address="wallet", money="10", money_id="id"
    )

    try:
        reasoning_auth(settings)
    except ValueError as exc:
        assert "REASONING_PRIVATE_KEY" in str(exc)
    else:
        raise AssertionError("Expected private key requirement")


def test_reasoning_auth_requires_money(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    settings = Settings(
        wallet_chain="ltc", wallet_address="wallet", money="", money_id="id"
    )

    try:
        reasoning_auth(settings)
    except ValueError as exc:
        assert "reasoning money is required" in str(exc)
    else:
        raise AssertionError("Expected money requirement")


def test_reasoning_auth_requires_wallet_chain(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    settings = Settings(
        wallet_chain="", wallet_address="wallet", money="10", money_id="id"
    )

    try:
        reasoning_auth(settings)
    except ValueError as exc:
        assert "reasoning wallet chain must be one of" in str(exc)
    else:
        raise AssertionError("Expected wallet chain requirement")
