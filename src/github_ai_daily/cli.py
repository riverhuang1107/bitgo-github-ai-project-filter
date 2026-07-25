from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from .config import (
    DEFAULT_MODEL,
    Settings,
    WalletProfile,
    default_config_path,
    user_config_dir,
)
from .bff import BFFClient, BFFTier1Auth, DEFAULT_BFF_BASE_URL, build_tier1_x_params
from .crypto import (
    WalletAuth,
    generate_money_id,
    generate_private_key,
    generate_wallet,
    build_x_params,
    load_private_key,
    load_private_key_pem,
)
from .gmail import authorize_gmail, parse_recipients, send_report_email
from .github import GitHubClient
from .mail import (
    SMTP_KEY,
    create_message,
    management_key_from_env,
    provision_mail,
    remove_mail,
    send_message,
)
from .reasoning import ReasoningClient
from .model_check import (
    LOCAL_MODEL_SOURCE,
    MODEL_GUIDE_URL,
    MODELS,
    WalletBalance,
    fetch_models_from_web,
    load_model_catalog,
    model_catalog_path,
    run_model_check,
    save_model_catalog,
    wallet_balance_from_response,
)
from .reports import build_items, write_model_check_reports, write_reports
from .secrets import get_secret_store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="github-ai-daily")
    root.add_argument("--config", type=Path, default=default_config_path())
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize keys, configuration and SMTP")
    init.add_argument("--no-git", action="store_true")
    init.add_argument("--skip-mail-verification", action="store_true")

    keygen = sub.add_parser("keygen", help="Generate the ECDSA private key")
    keygen.add_argument("--path", type=Path)
    keygen.add_argument("--force", action="store_true")

    generate = sub.add_parser("generate", help="Generate daily reports")
    _report_args(generate)

    send = sub.add_parser("send", help="Send an existing HTML report")
    send.add_argument("html", type=Path)
    send.add_argument("--to", required=True)
    send.add_argument("--attach", action="append", type=Path, default=[])

    run = sub.add_parser("run", help="Generate and optionally email reports")
    _report_args(run)
    run.add_argument("--to")

    model_check = sub.add_parser(
        "model-check", help="Test every Bitgo model listed in the product guide appendix"
    )
    model_check.add_argument("--output-dir", type=Path)
    model_check.add_argument("--max-tokens", type=int, default=128)
    model_check.add_argument(
        "--read-web-models",
        action="store_true",
        help="Fetch the latest model list from the Bitgo product guide instead of using the local list",
    )
    model_check.add_argument("--bff-base-url", default=DEFAULT_BFF_BASE_URL)
    model_check.add_argument("--send-email", action="store_true")
    model_check.add_argument("--to", help="Comma-separated Gmail recipients")
    _wallet_args(
        model_check,
        money_id_help="Persistent money_id required for the reused Bitgo sub-wallet",
    )
    model_check.add_argument(
        "--key", type=Path, help="ECDSA interface signing key path"
    )

    gmail_auth = sub.add_parser("gmail-auth", help="Authorize Gmail API report delivery")
    gmail_auth.add_argument("--force", action="store_true")
    gmail_auth.add_argument(
        "--console", action="store_true", help="Use a pasted browser redirect URL"
    )

    mail = sub.add_parser("mail", help="Manage SMTP credentials")
    mail_sub = mail.add_subparsers(dest="mail_command", required=True)
    mail_sub.add_parser("status")
    test = mail_sub.add_parser("test")
    test.add_argument("--to")
    mail_sub.add_parser("rotate")
    mail_sub.add_parser("remove")

    reasoning = sub.add_parser("reasoning", help="Test the external reasoning API")
    reasoning_sub = reasoning.add_subparsers(dest="reasoning_command", required=True)
    reasoning_test = reasoning_sub.add_parser("test")
    reasoning_test.add_argument("--model")
    _wallet_args(reasoning_test)
    reasoning_test.add_argument(
        "--key", type=Path, help="ECDSA interface signing key path"
    )

    bff = sub.add_parser("bff", help="Query Bitgo BFF wallet APIs")
    bff_sub = bff.add_subparsers(dest="bff_command", required=True)
    bff_wallet = bff_sub.add_parser(
        "wallet", help="Fetch Tier1 wallet information and recharge transactions"
    )
    bff_wallet.add_argument("--base-url", default=DEFAULT_BFF_BASE_URL)
    bff_wallet.add_argument("--chain", choices=["ltc", "btc", "eth"], required=True)
    bff_wallet.add_argument("--wallet-address", required=True)
    bff_wallet.add_argument("--private-key")
    bff_wallet.add_argument("--signer-command")
    bff_wallet.add_argument("--page", type=int, default=1)
    bff_wallet.add_argument("--page-size", type=int, default=20)
    return root


def _report_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--limit", type=int, default=10)
    command.add_argument(
        "--format", choices=["markdown", "html", "both"], default="both"
    )
    command.add_argument(
        "--date", help="Report date label in YYYY-MM-DD; collection is live"
    )
    command.add_argument("--output-dir", type=Path)
    _wallet_args(command)


def _wallet_args(
    command: argparse.ArgumentParser,
    money_id_help: str = "Optional existing authorization money_id; generated automatically when omitted",
) -> None:
    command.add_argument("--chain", choices=["ltc", "btc", "eth"])
    command.add_argument("--wallet-address")
    command.add_argument("--money")
    command.add_argument(
        "--money-id",
        help=money_id_help,
    )
    command.add_argument("--private-key")
    command.add_argument("--signer-command")
    command.add_argument(
        "--new-wallet",
        action="store_true",
        help="Generate a fresh wallet for this request instead of reusing a configured wallet",
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return dispatch(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def dispatch(args) -> int:
    settings = Settings.load(args.config)
    if args.command == "init":
        return cmd_init(args, settings)
    if args.command == "keygen":
        path = args.path or user_config_dir() / "ecdsa-private.pem"
        generate_private_key(path, args.force)
        print(path)
        return 0
    if args.command == "generate":
        paths = generate(settings, args)
        _print_paths(paths)
        return 0
    if args.command == "send":
        send_existing(settings, args.html, args.to, args.attach)
        return 0
    if args.command == "run":
        paths = generate(settings, args)
        _print_paths(paths)
        if args.to:
            html_path = paths.get("html")
            if not html_path:
                raise RuntimeError(
                    "Email requires HTML output; use --format html or both"
                )
            send_existing(settings, html_path, args.to, list(paths.values()))
        return 0
    if args.command == "model-check":
        return cmd_model_check(args, settings)
    if args.command == "gmail-auth":
        return cmd_gmail_auth(args)
    if args.command == "mail":
        return cmd_mail(args, settings)
    if args.command == "reasoning":
        return cmd_reasoning(args, settings)
    if args.command == "bff":
        return cmd_bff(args)
    raise RuntimeError("Unknown command")


def cmd_init(args, settings: Settings) -> int:
    if not args.no_git and not Path(".git").exists():
        subprocess.run(["git", "init"], check=True)
    key_path = (
        Path(settings.private_key_path)
        if settings.private_key_path
        else user_config_dir() / "ecdsa-private.pem"
    )
    if not key_path.exists():
        generate_private_key(key_path)
    settings.private_key_path = str(key_path)
    settings.model = (
        os.environ.get("REASONING_API_MODEL") or settings.model or DEFAULT_MODEL
    )
    settings.mail_from = os.environ.get("GITHUB_AI_MAIL_FROM") or settings.mail_from
    settings.mail_test_to = settings.mail_test_to or os.environ.get(
        "GITHUB_AI_MAIL_TEST_TO", ""
    )
    if not settings.mail_test_to:
        raise RuntimeError("GITHUB_AI_MAIL_TEST_TO is required")
    store = get_secret_store()
    management_key = management_key_from_env()
    try:
        provision_mail(settings, store, management_key, not args.skip_mail_verification)
    finally:
        management_key = ""
    settings.save(args.config)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    print(f"Initialized configuration: {args.config}")
    return 0


def generate(settings: Settings, args) -> dict[str, Path]:
    if args.limit < 1:
        raise ValueError("--limit must be greater than zero")
    if not settings.model:
        raise RuntimeError("Tool is not initialized; run `github-ai-daily init`")
    github = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    auth = reasoning_auth(settings, args)
    reasoning = ReasoningClient(
        reasoning_endpoint(settings), settings.model, auth, reasoning_interface_key(settings)
    )
    try:
        repos = github.enrich(github.trending())
        selections = reasoning.select(repos)
    finally:
        print(reasoning.last_usage.format_json())
        github.close()
        reasoning.close()
    items = build_items(repos, selections, args.limit)
    if not items:
        raise RuntimeError("Reasoning API selected no AI projects")
    generated_at = datetime.now().astimezone()
    if args.date:
        requested = date.fromisoformat(args.date)
        generated_at = generated_at.replace(
            year=requested.year, month=requested.month, day=requested.day
        )
    output_dir = args.output_dir or Path(settings.output_dir)
    return write_reports(items, output_dir, args.format, generated_at)


def send_existing(
    settings: Settings, html_path: Path, recipient: str, attachments: list[Path]
) -> None:
    html_body = html_path.read_text(encoding="utf-8")
    message = create_message(
        settings.mail_from,
        recipient,
        f"GitHub 热门 AI 项目日报 {datetime.now().date().isoformat()}",
        html_body,
        attachments,
    )
    send_message(settings, get_secret_store(), message)
    print(f"Sent report to {recipient}")


def cmd_mail(args, settings: Settings) -> int:
    store = get_secret_store()
    if args.mail_command == "status":
        print("configured" if store.get(SMTP_KEY) else "not configured")
        return 0
    if args.mail_command == "test":
        recipient = args.to or settings.mail_test_to
        if not recipient:
            raise RuntimeError("A recipient is required via --to or mail.test_to")
        message = create_message(
            settings.mail_from,
            recipient,
            "GitHub AI Daily SMTP 测试",
            "<p>SMTP 测试成功。</p>",
        )
        send_message(settings, store, message)
        print(f"Sent test email to {recipient}")
        return 0
    if args.mail_command == "rotate":
        management_key = management_key_from_env()
        try:
            provision_mail(settings, store, management_key, True)
        finally:
            management_key = ""
        print("SMTP credential rotated")
        return 0
    if args.mail_command == "remove":
        key = os.environ.pop("RESEND_MANAGEMENT_API_KEY", None)
        try:
            remove_mail(store, key)
        finally:
            key = ""
        print("SMTP credential removed")
        return 0
    raise RuntimeError("Unknown mail command")


def cmd_reasoning(args, settings: Settings) -> int:
    if args.reasoning_command != "test":
        raise RuntimeError("Unknown reasoning command")
    model = (
        args.model
        or os.environ.get("REASONING_API_MODEL")
        or settings.model
        or DEFAULT_MODEL
    )
    if not model:
        raise RuntimeError("Provide --model or REASONING_API_MODEL")
    auth = reasoning_auth(settings, args)
    reasoning = ReasoningClient(
        reasoning_endpoint(settings), model, auth, reasoning_interface_key(settings, args)
    )
    try:
        response = reasoning.test_access()
        if not isinstance(response, dict) or not response.get("content"):
            raise RuntimeError(
                "API responded, but no Anthropic-style content was returned"
            )
        print("External reasoning API access: OK")
    finally:
        print(reasoning.last_usage.format_json())
        reasoning.close()
    return 0


def cmd_model_check(args, settings: Settings) -> int:
    if getattr(args, "new_wallet", False):
        raise ValueError("model-check must reuse an existing wallet and money_id")
    auth = reasoning_auth(settings, args)
    if _persist_generated_model_check_money_id(settings, args, auth):
        print(f"Money ID: {auth.money_id} (generated and saved for reuse)", flush=True)
    else:
        print(f"Money ID: {auth.money_id} (reused for every model-check run and call)", flush=True)
    catalog_path = model_catalog_path(getattr(args, "config", None) or default_config_path())
    models = MODELS
    model_source = LOCAL_MODEL_SOURCE
    if getattr(args, "read_web_models", False):
        print(f"Fetching current model list from: {MODEL_GUIDE_URL}", flush=True)
        models = fetch_models_from_web()
        catalog = save_model_catalog(catalog_path, models)
        model_source = f"本地模型缓存（本次从网页更新）：{catalog_path}（{len(models)} 个模型）"
        print(f"Loaded and saved {len(models)} models to: {catalog_path}", flush=True)
    else:
        catalog = load_model_catalog(catalog_path)
        if catalog is not None:
            models = catalog.models
            model_source = (
                f"本地模型缓存：{catalog_path}"
                f"（{len(models)} 个模型，更新于 {catalog.fetched_at.isoformat(timespec='seconds')}）"
            )
            print(f"Using local model catalog: {catalog_path} ({len(models)} models)", flush=True)
    client = ReasoningClient(
        reasoning_endpoint(settings), settings.model or DEFAULT_MODEL, auth, reasoning_interface_key(settings, args)
    )
    try:
        report = run_model_check(
            client,
            max_tokens=args.max_tokens,
            models=models,
            model_source=model_source,
        )
    finally:
        client.close()
    report.money_id = auth.money_id
    report.wallet_balance = fetch_latest_sub_wallet_balance(auth, args.bff_base_url)
    output_dir = args.output_dir or Path(settings.output_dir)
    paths = write_model_check_reports(report, output_dir)
    _print_paths(paths)
    print(
        f"Model check complete: success={report.success_count}, failures={len(report.failures)}, "
        f"input_tokens={report.input_tokens}, output_tokens={report.output_tokens}, "
        f"reported_cost={report.reported_cost:.8f}"
    )
    if args.send_email:
        recipients = parse_recipients(args.to or os.environ.get("REPORT_RECIPIENTS", ""))
        if not recipients:
            raise RuntimeError("Email recipients are required via --to or REPORT_RECIPIENTS")
        html_body = paths["html"].read_text(encoding="utf-8")
        send_report_email(
            html_body,
            recipients,
            f"Bitgo 大模型连通性报告 {report.generated_at.date().isoformat()}",
            list(paths.values()),
        )
        print(f"Sent Gmail report to {', '.join(recipients)}")
    return 0


def fetch_latest_sub_wallet_balance(auth: WalletAuth, base_url: str) -> WalletBalance:
    print("Fetching latest Bitgo sub-wallet balance...", flush=True)
    retrieved_at = datetime.now().astimezone()
    try:
        x_params = build_x_params(auth)
        client = BFFClient(base_url)
        try:
            data = client.get_sub_wallet(x_params)
        finally:
            client.close()
        snapshot = wallet_balance_from_response(data, retrieved_at, auth.money_id)
    except Exception as exc:
        snapshot = WalletBalance(retrieved_at=retrieved_at, money_id=auth.money_id, error=str(exc))
    if snapshot.error:
        print(f"Sub-wallet balance unavailable: {snapshot.error}", flush=True)
    else:
        print(
            f"Latest sub-wallet balance: {snapshot.balance} USD"
            + (f" (coin type: {snapshot.coin_type})" if snapshot.coin_type else ""),
            flush=True,
        )
    return snapshot


def cmd_gmail_auth(args) -> int:
    path = authorize_gmail(force=args.force, console=args.console)
    print(f"Gmail OAuth token saved to: {path}")
    return 0


def cmd_bff(args) -> int:
    if args.bff_command != "wallet":
        raise RuntimeError("Unknown BFF command")
    if args.page < 1:
        raise ValueError("--page must be greater than zero")
    if args.page_size < 1:
        raise ValueError("--page-size must be greater than zero")
    private_key = (
        args.private_key
        or os.environ.get(_chain_env_name(args.chain, "PRIVATE_KEY"))
        or os.environ.get("BFF_PRIVATE_KEY")
        or os.environ.get("REASONING_PRIVATE_KEY")
    )
    auth = BFFTier1Auth(
        chain=args.chain,
        wallet_address=args.wallet_address,
        private_key=private_key or "",
        signer_command=args.signer_command or "",
    )
    x_params = build_tier1_x_params(auth)
    client = BFFClient(args.base_url)
    try:
        wallet = client.get_wallet(x_params)
        transactions = client.get_transactions(
            x_params, page=args.page, page_size=args.page_size
        )
    finally:
        client.close()
    print(
        json.dumps(
            {
                "wallet": wallet,
                "transactions": transactions,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def reasoning_auth(settings: Settings, args=None) -> WalletAuth:
    explicit_chain = _arg_or_env(args, "chain", "REASONING_WALLET_CHAIN", "")
    chain = explicit_chain or settings.wallet_chain
    profile = _wallet_profile(settings, chain)
    signer_command = _wallet_value(
        args,
        settings,
        profile,
        chain,
        "signer_command",
        "REASONING_SIGNER_COMMAND",
    )
    use_new_wallet = _arg_bool_or_env(args, "new_wallet", "REASONING_NEW_WALLET")
    generated = generate_wallet(chain, signer_command) if use_new_wallet else None
    private_key = (
        generated.private_key if generated else _private_key_for_chain(args, chain)
    )
    configured_money_id = _wallet_value(
        args, settings, profile, chain, "money_id", "REASONING_MONEY_ID"
    )
    money_id = generate_money_id() if use_new_wallet else configured_money_id
    if not money_id:
        money_id = generate_money_id()
    auth = WalletAuth(
        chain=chain,
        wallet_address=(
            generated.wallet_address
            if generated
            else _wallet_value(
                args,
                settings,
                profile,
                chain,
                "wallet_address",
                "REASONING_WALLET_ADDRESS",
            )
        ),
        money=_wallet_value(args, settings, profile, chain, "money", "REASONING_MONEY"),
        money_id=money_id,
        private_key=private_key,
        signer_command=signer_command,
    )
    auth.validate()
    return auth


def _persist_generated_model_check_money_id(
    settings: Settings, args, auth: WalletAuth
) -> bool:
    profile = _wallet_profile(settings, auth.chain)
    configured_money_id = _wallet_value(
        args, settings, profile, auth.chain, "money_id", "REASONING_MONEY_ID"
    )
    if configured_money_id:
        return False
    settings.wallets[auth.normalized_chain()] = WalletProfile(
        wallet_address=auth.wallet_address,
        money=auth.money,
        money_id=auth.money_id,
        signer_command=auth.signer_command,
    )
    config_path = getattr(args, "config", None) or default_config_path()
    settings.save(config_path)
    return True


def reasoning_interface_key(settings: Settings, args=None):
    configured = getattr(args, "key", None) if args is not None else None
    if not configured:
        pem = os.environ.get("REASONING_INTERFACE_PRIVATE_KEY_PEM")
        if pem:
            return load_private_key_pem(pem)
    key_path = configured or (
        Path(settings.private_key_path)
        if settings.private_key_path
        else user_config_dir() / "ecdsa-private.pem"
    )
    if not key_path.exists():
        raise RuntimeError(
            "Reasoning interface ECDSA key is required; run "
            f"`github-ai-daily keygen --path {key_path}`"
        )
    return load_private_key(key_path)


def reasoning_endpoint(settings: Settings) -> str:
    return os.environ.get("REASONING_API_ENDPOINT") or settings.endpoint


def _arg_or_env(args, attr: str, env_name: str, default: str) -> str:
    value = getattr(args, attr, None) if args is not None else None
    if value:
        return str(value)
    return os.environ.get(env_name) or default


def _arg_bool_or_env(args, attr: str, env_name: str) -> bool:
    value = getattr(args, attr, False) if args is not None else False
    if value:
        return True
    env_value = os.environ.get(env_name, "")
    return env_value.strip().lower() in {"1", "true", "yes", "on"}


def _private_key_for_chain(args, chain: str) -> str:
    value = getattr(args, "private_key", None) if args is not None else None
    if value:
        return str(value)
    chain_env = _chain_env_name(chain, "PRIVATE_KEY")
    if chain_env:
        chain_value = os.environ.get(chain_env)
        if chain_value:
            return chain_value
    return os.environ.get("REASONING_PRIVATE_KEY", "")


def _wallet_profile(settings: Settings, chain: str) -> WalletProfile | None:
    normalized = chain.strip().lower()
    if not normalized:
        return None
    return settings.wallets.get(normalized)


def _wallet_value(
    args,
    settings: Settings,
    profile: WalletProfile | None,
    chain: str,
    attr: str,
    env_name: str,
) -> str:
    value = getattr(args, attr, None) if args is not None else None
    if value:
        return str(value)
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    if profile is not None:
        profile_value = getattr(profile, attr)
        if profile_value:
            return str(profile_value)
    if _matches_legacy_wallet(settings, chain):
        return str(getattr(settings, attr))
    return ""


def _matches_legacy_wallet(settings: Settings, chain: str) -> bool:
    return (
        bool(chain) and settings.wallet_chain.strip().lower() == chain.strip().lower()
    )


def _chain_env_name(chain: str, suffix: str) -> str:
    normalized = chain.strip().upper()
    if normalized not in {"LTC", "BTC", "ETH"}:
        return ""
    return f"REASONING_{normalized}_{suffix}"


def _print_paths(paths: dict[str, Path]) -> None:
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
