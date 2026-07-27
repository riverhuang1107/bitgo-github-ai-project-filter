from argparse import Namespace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from github_ai_daily.cli import (
    _persist_model_check_money_id,
    cmd_init,
    cmd_model_check,
    parser,
    reasoning_auth,
    send_model_check_report,
)
from github_ai_daily.config import DEFAULT_MAIL_FROM, Settings, WalletProfile
from github_ai_daily.crypto import WalletAuth
from github_ai_daily.model_check import (
    ModelCheckReport,
    ModelCheckResult,
    ModelDefinition,
    load_model_catalog,
    save_model_catalog,
)


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


def test_reasoning_auth_finds_wallet_chain_by_money_id(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "generic-private")
    settings = Settings(
        wallets={
            "btc": WalletProfile(
                wallet_address="btc-wallet",
                money="5",
                money_id="btc-money-id",
            ),
            "eth": WalletProfile(
                wallet_address="0xwallet",
                money="10",
                money_id="eth-money-id",
            ),
        }
    )
    args = Namespace(
        private_key=None,
        chain=None,
        wallet_address=None,
        money=None,
        money_id="btc-money-id",
        signer_command=None,
    )

    auth = reasoning_auth(settings, args, allow_new_wallet=False)

    assert auth.chain == "btc"
    assert auth.wallet_address == "btc-wallet"
    assert auth.money == "5"
    assert auth.money_id == "btc-money-id"
    assert auth.private_key == "generic-private"


def test_reasoning_private_key_generic_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "generic-private")
    monkeypatch.setenv("REASONING_BTC_PRIVATE_KEY", "chain-private")
    settings = Settings(
        wallets={
            "btc": WalletProfile(
                wallet_address="btc-wallet",
                money="5",
                money_id="btc-money-id",
            )
        }
    )
    args = Namespace(
        private_key=None,
        chain="btc",
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
    )

    auth = reasoning_auth(settings, args, allow_new_wallet=False)

    assert auth.private_key == "generic-private"


def test_model_check_missing_money_id_is_generated_and_saved_to_single_config(monkeypatch, tmp_path):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    monkeypatch.delenv("REASONING_MONEY_ID", raising=False)
    monkeypatch.setattr("github_ai_daily.cli.generate_money_id", lambda: "new-id")
    config_path = tmp_path / "config.toml"
    settings = Settings(
        wallet_chain="btc", wallet_address="wallet-a", money="5", money_id=""
    )
    args = Namespace(
        private_key=None,
        chain="btc",
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
        config=config_path,
    )

    auth = reasoning_auth(settings, args)

    assert auth.money_id == "new-id"
    assert auth.money_id_created is True
    _persist_model_check_money_id(settings, args, auth)

    saved = Settings.load(config_path)
    assert saved.money_id == "new-id"
    assert saved.wallet_chain == "btc"
    assert saved.wallet_address == "wallet-a"


def test_model_check_uses_single_config_instead_of_legacy_wallet_profile(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    settings = Settings(
        wallet_chain="btc",
        wallet_address="current-wallet",
        money="5",
        money_id="current-id",
        wallets={
            "btc": WalletProfile(
                chain="btc",
                wallet_address="legacy-wallet",
                money="5",
                money_id="legacy-id",
            )
        },
    )
    args = Namespace(
        private_key=None,
        chain=None,
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
    )

    auth = reasoning_auth(settings, args, use_wallet_profiles=False)

    assert auth.wallet_address == "current-wallet"
    assert auth.money_id == "current-id"


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


def test_model_check_generates_missing_money_id(monkeypatch):
    monkeypatch.setenv("REASONING_PRIVATE_KEY", "private")
    settings = Settings(wallet_chain="ltc", wallet_address="wallet", money="10")
    args = Namespace(
        private_key=None,
        chain=None,
        wallet_address=None,
        money=None,
        money_id=None,
        signer_command=None,
        new_wallet=False,
    )

    auth = reasoning_auth(settings, args)

    assert auth.money_id.startswith("money_")


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


def test_model_check_command_reports_partial_failure_without_failing(monkeypatch, tmp_path):
    model = ModelDefinition("bad", "Bad", "Test", Decimal("1"), Decimal("2"))
    report = ModelCheckReport(
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        prompt="test",
        max_tokens=128,
        results=[
            ModelCheckResult(
                model=model,
                started_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
                duration_ms=10,
                ok=False,
                status_code=400,
                error_category="模型不可用",
                error_message="invalid model",
            )
        ],
    )

    class FakeClient:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    auth = WalletAuth("eth", "0xwallet", "10", "shared-id", "private")
    monkeypatch.setattr("github_ai_daily.cli.reasoning_auth", lambda settings, args, **kwargs: auth)
    monkeypatch.setattr("github_ai_daily.cli.reasoning_interface_key", lambda settings, args: object())
    monkeypatch.setattr("github_ai_daily.cli.ReasoningClient", FakeClient)
    monkeypatch.setattr("github_ai_daily.cli.run_model_check", lambda client, max_tokens, **kwargs: report)
    monkeypatch.setattr(
        "github_ai_daily.cli.fetch_latest_sub_wallet_balance",
        lambda auth, base_url: SimpleNamespace(error="BFF unavailable"),
    )
    args = Namespace(
        output_dir=tmp_path,
        max_tokens=128,
        send_email=False,
        to=None,
        money_id="explicit-id",
        bff_base_url="https://bitgo.example.test",
    )

    assert cmd_model_check(args, Settings()) == 0
    assert list(tmp_path.glob("bitgo-model-check_*.html"))


def test_model_check_reuses_the_configured_money_id(monkeypatch, tmp_path):
    captured = {}
    report = ModelCheckReport(
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        prompt="test",
        max_tokens=128,
        results=[],
    )

    class FakeClient:
        def __init__(self, endpoint, model, auth, interface_key):
            captured["money_id"] = auth.money_id

        def close(self):
            pass

    auth = WalletAuth("eth", "0xwallet", "10", "old-id", "private")
    monkeypatch.setattr("github_ai_daily.cli.reasoning_auth", lambda settings, args, **kwargs: auth)
    monkeypatch.setattr("github_ai_daily.cli.reasoning_interface_key", lambda settings, args: object())
    monkeypatch.setattr("github_ai_daily.cli.ReasoningClient", FakeClient)
    monkeypatch.setattr("github_ai_daily.cli.run_model_check", lambda client, max_tokens, **kwargs: report)
    monkeypatch.setattr(
        "github_ai_daily.cli.fetch_latest_sub_wallet_balance",
        lambda auth, base_url: SimpleNamespace(error="BFF unavailable"),
    )
    args = Namespace(
        output_dir=tmp_path,
        max_tokens=128,
        send_email=False,
        to=None,
        money_id="old-id",
        bff_base_url="https://bitgo.example.test",
    )

    assert cmd_model_check(args, Settings()) == 0
    assert captured["money_id"] == "old-id"


def test_model_check_reads_web_models_and_updates_local_catalog(monkeypatch, tmp_path):
    captured = {}
    web_models = (ModelDefinition("web-model", "Web", "Test", Decimal("1"), Decimal("2")),)
    report = ModelCheckReport(
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        prompt="test",
        max_tokens=128,
        results=[],
    )

    class FakeClient:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    auth = WalletAuth("eth", "0xwallet", "10", "old-id", "private")
    monkeypatch.setattr("github_ai_daily.cli.reasoning_auth", lambda settings, args, **kwargs: auth)
    monkeypatch.setattr("github_ai_daily.cli.reasoning_interface_key", lambda settings, args: object())
    monkeypatch.setattr("github_ai_daily.cli.ReasoningClient", FakeClient)
    monkeypatch.setattr("github_ai_daily.cli.fetch_models_from_web", lambda: web_models)
    monkeypatch.setattr(
        "github_ai_daily.cli.run_model_check",
        lambda client, max_tokens, **kwargs: captured.update(kwargs) or report,
    )
    monkeypatch.setattr(
        "github_ai_daily.cli.fetch_latest_sub_wallet_balance",
        lambda auth, base_url: SimpleNamespace(error="BFF unavailable"),
    )
    args = Namespace(
        config=tmp_path / "config.toml",
        output_dir=tmp_path,
        max_tokens=128,
        read_web_models=True,
        send_email=False,
        to=None,
        money_id="old-id",
        bff_base_url="https://bitgo.example.test",
    )

    assert cmd_model_check(args, Settings()) == 0
    assert captured["models"] == web_models
    assert "本次从网页更新" in captured["model_source"]
    assert load_model_catalog(tmp_path / "model_catalog.json").models == web_models


def test_model_check_uses_existing_local_catalog_without_fetching(monkeypatch, tmp_path):
    cached_models = (ModelDefinition("cached-model", "Cached", "Test", Decimal("1"), Decimal("2")),)
    save_model_catalog(tmp_path / "model_catalog.json", cached_models)
    captured = {}
    report = ModelCheckReport(
        generated_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
        prompt="test",
        max_tokens=128,
        results=[],
    )

    class FakeClient:
        def __init__(self, *args):
            pass

        def close(self):
            pass

    auth = WalletAuth("eth", "0xwallet", "10", "old-id", "private")
    monkeypatch.setattr("github_ai_daily.cli.reasoning_auth", lambda settings, args, **kwargs: auth)
    monkeypatch.setattr("github_ai_daily.cli.reasoning_interface_key", lambda settings, args: object())
    monkeypatch.setattr("github_ai_daily.cli.ReasoningClient", FakeClient)
    monkeypatch.setattr(
        "github_ai_daily.cli.fetch_models_from_web",
        lambda: (_ for _ in ()).throw(AssertionError("default mode must not read the web")),
    )
    monkeypatch.setattr(
        "github_ai_daily.cli.run_model_check",
        lambda client, max_tokens, **kwargs: captured.update(kwargs) or report,
    )
    monkeypatch.setattr(
        "github_ai_daily.cli.fetch_latest_sub_wallet_balance",
        lambda auth, base_url: SimpleNamespace(error="BFF unavailable"),
    )
    args = Namespace(
        config=tmp_path / "config.toml",
        output_dir=tmp_path,
        max_tokens=128,
        read_web_models=False,
        send_email=False,
        to=None,
        money_id="old-id",
        bff_base_url="https://bitgo.example.test",
    )

    assert cmd_model_check(args, Settings()) == 0
    assert captured["models"] == cached_models
    assert "本地模型缓存" in captured["model_source"]


def test_parser_supports_model_check_and_gmail_auth():
    assert parser().parse_args(["model-check", "--send-email"]).command == "model-check"
    assert parser().parse_args(["model-check", "--read-web-models"]).read_web_models is True
    assert parser().parse_args(["model-check", "--model", "claude-4.6-opus", "--model", "deepseek-v3"]).model == ["claude-4.6-opus", "deepseek-v3"]
    assert parser().parse_args(["model-check", "--mail-backend", "agent"]).mail_backend == "agent"
    assert parser().parse_args(["model-check", "--new-money-id"]).new_money_id is True
    assert parser().parse_args(["model-check"]).protocol == []
    assert parser().parse_args(["model-check", "--protocol", "all"]).protocol == ["all"]
    assert parser().parse_args(["model-check", "--protocol", "messages,responses", "--protocol", "chat"]).protocol == ["messages,responses", "chat"]
    assert parser().parse_args(["gmail-auth", "--console"]).command == "gmail-auth"


def test_model_check_email_auto_prefers_agent_mail(monkeypatch, tmp_path):
    html = "<h1>Report</h1>"
    attachment = tmp_path / "report.md"
    attachment.write_text("# Report", encoding="utf-8")
    captured = {}

    monkeypatch.setattr("github_ai_daily.cli.agent_mail_available", lambda: True)
    monkeypatch.setattr(
        "github_ai_daily.cli.send_agent_message",
        lambda message: captured.update(message=message),
    )
    monkeypatch.setattr(
        "github_ai_daily.cli.send_report_email",
        lambda *args: (_ for _ in ()).throw(AssertionError("Gmail must not be used")),
    )

    backend = send_model_check_report(
        Settings(),
        html,
        ["one@example.com", "two@example.com"],
        "Model report",
        [attachment],
    )

    assert backend == "Agent Mail"
    assert captured["message"]["To"] == "one@example.com, two@example.com"
    body = captured["message"].get_body(preferencelist=("html",)).get_content().strip()
    assert "connectivity report is ready" in body
    assert html not in body
    assert [part.get_filename() for part in captured["message"].iter_attachments()] == ["report.md"]
