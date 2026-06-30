from argparse import Namespace

from github_ai_daily.cli import cmd_init, reasoning_auth
from github_ai_daily.config import DEFAULT_MAIL_FROM, Settings


def test_init_does_not_require_mail_from(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.delenv("GITHUB_AI_MAIL_FROM", raising=False)
    monkeypatch.setenv("GITHUB_AI_MAIL_TEST_TO", "reader@example.com")
    monkeypatch.setattr("github_ai_daily.cli.generate_private_key", lambda path: None)
    monkeypatch.setattr("github_ai_daily.cli.get_secret_store", lambda: object())
    monkeypatch.setattr("github_ai_daily.cli.management_key_from_env", lambda: "management")
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
    args = Namespace(config=tmp_path / "config.toml", no_git=True, skip_mail_verification=True)

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
    args = Namespace(config=tmp_path / "config.toml", no_git=True, skip_mail_verification=True)

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


def test_reasoning_auth_requires_private_key(monkeypatch):
    monkeypatch.delenv("REASONING_PRIVATE_KEY", raising=False)
    settings = Settings(wallet_chain="ltc", wallet_address="wallet", money="10", money_id="id")

    try:
        reasoning_auth(settings)
    except ValueError as exc:
        assert "REASONING_PRIVATE_KEY" in str(exc)
    else:
        raise AssertionError("Expected private key requirement")


def test_reasoning_auth_requires_money(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    settings = Settings(wallet_chain="ltc", wallet_address="wallet", money="", money_id="id")

    try:
        reasoning_auth(settings)
    except ValueError as exc:
        assert "reasoning money is required" in str(exc)
    else:
        raise AssertionError("Expected money requirement")


def test_reasoning_auth_requires_wallet_chain(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    settings = Settings(wallet_chain="", wallet_address="wallet", money="10", money_id="id")

    try:
        reasoning_auth(settings)
    except ValueError as exc:
        assert "reasoning wallet chain must be one of" in str(exc)
    else:
        raise AssertionError("Expected wallet chain requirement")
