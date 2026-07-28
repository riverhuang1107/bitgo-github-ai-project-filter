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
    agent_mail_available,
    create_message,
    management_key_from_env,
    provision_mail,
    remove_mail,
    send_agent_message,
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
    select_models,
    select_protocols,
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
        "model-check",
        help="Test Bitgo model connectivity with selected API protocols",
        description="Test one or more Bitgo models with the selected API protocols. "
        "By default, Anthropic Messages and OpenAI Chat Completions are tested.",
        epilog=(
            "Examples:\n"
            "  github-ai-daily model-check --model openai/gpt-5-mini\n"
            "  github-ai-daily model-check --protocol responses --model openai/gpt-5-mini\n"
            "  github-ai-daily model-check --protocol all\n"
            "  github-ai-daily model-check --protocol messages,responses"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    model_check.add_argument("--output-dir", type=Path, help="Directory for the HTML and Markdown reports")
    model_check.add_argument("--max-tokens", type=int, default=128, help="Maximum output tokens per model request (default: 128)")
    model_check.add_argument(
        "--protocol",
        action="append",
        default=[],
        metavar="NAME",
        help="Protocol to test: messages, chat, responses, or all; repeat or separate multiple values with commas (default: messages,chat)",
    )
    model_check.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model ID or displayed name to test; repeat or separate multiple values with commas",
    )
    model_check.add_argument(
        "--read-web-models",
        action="store_true",
        help="Fetch the latest model list from the Bitgo product guide instead of using the local list",
    )
    model_check.add_argument(
        "--check-input-cache",
        action="store_true",
        help=(
            "Run the minimal two-request input-cache verification for exactly one "
            "model using only the Anthropic Messages protocol"
        ),
    )
    model_check.add_argument("--bff-base-url", default=DEFAULT_BFF_BASE_URL, help="Bitgo BFF base URL used to read the final sub-wallet balance")
    model_check.add_argument("--send-email", action="store_true", help="Email the completed report")
    model_check.add_argument("--to", help="Comma-separated Gmail recipients")
    model_check.add_argument(
        "--mail-backend",
        choices=("auto", "agent", "gmail"),
        default=os.environ.get("MODEL_CHECK_MAIL_BACKEND", "auto"),
        help="Report email backend: Agent Mail when available, Gmail OAuth otherwise",
    )
    _wallet_args(
        model_check,
        money_id_help="Persistent money_id required for the reused Bitgo sub-wallet",
        allow_new_wallet=False,
    )
    model_check.add_argument(
        "--new-money-id",
        action="store_true",
        help="Generate a new money_id for this run instead of reusing an existing one",
    )
    model_check.add_argument("--key", type=Path, help="Path to the interface ECDSA signing key")

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
    bff_sub_wallet = bff_sub.add_parser(
        "sub-wallet", help="Fetch a Tier2 sub-wallet and its consumption orders"
    )
    bff_sub_wallet.add_argument("--base-url", default=DEFAULT_BFF_BASE_URL)
    _wallet_args(
        bff_sub_wallet,
        money_id_help="Existing money_id identifying the Bitgo sub-wallet",
        allow_new_wallet=False,
    )
    bff_sub_wallet.add_argument("--page", type=int, default=1)
    bff_sub_wallet.add_argument("--page-size", type=int, default=20)
    bff_sub_wallet.add_argument("--user-id", default="")
    bff_sub_wallet.add_argument("--category", choices=["TOKEN", "VPS"])
    bff_sub_wallet.add_argument(
        "--type", dest="order_type", choices=["deduct", "refund"]
    )
    bff_sub_wallet.add_argument("--start-time", default="")
    bff_sub_wallet.add_argument("--end-time", default="")
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
    *,
    allow_new_wallet: bool = True,
) -> None:
    command.add_argument("--chain", choices=["ltc", "btc", "eth"], help="Self-custody wallet chain")
    command.add_argument("--wallet-address", help="Self-custody wallet address used for authorization")
    command.add_argument("--money", help="Authorized sub-wallet amount; must match the money_id record")
    command.add_argument(
        "--money-id",
        help=money_id_help,
    )
    command.add_argument("--private-key", help="Wallet private key supplied only at runtime; prefer a secure environment variable")
    command.add_argument("--signer-command", help="Optional command that performs wallet signatures")
    if allow_new_wallet:
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
        return cmd_bff(args, settings)
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
    new_money_id = getattr(args, "new_money_id", False)
    if new_money_id and getattr(args, "money_id", None):
        raise ValueError("--new-money-id cannot be combined with --money-id")
    if new_money_id:
        args.money_id = generate_money_id()
    auth = reasoning_auth(settings, args, use_wallet_profiles=False)
    if new_money_id:
        auth.money_id_created = True
    if auth.money_id_created:
        _persist_model_check_money_id(settings, args, auth)
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
    requested_models = getattr(args, "model", [])
    if requested_models:
        models = select_models(models, requested_models)
        model_source += f"；筛选模型：{', '.join(model.model_id for model in models)}"
        print(f"Testing selected models: {', '.join(model.model_id for model in models)}", flush=True)
    protocols = select_protocols(getattr(args, "protocol", []))
    input_cache_check = getattr(args, "check_input_cache", False)
    if input_cache_check:
        if len(models) != 1:
            raise ValueError("--check-input-cache requires exactly one --model")
        if getattr(args, "protocol", []) and protocols != ("Anthropic Messages",):
            raise ValueError("--check-input-cache only supports --protocol messages")
        protocols = ("Anthropic Messages",)
    print(f"Testing protocols: {', '.join(protocols)}", flush=True)
    client = ReasoningClient(
        reasoning_endpoint(settings), settings.model or DEFAULT_MODEL, auth, reasoning_interface_key(settings, args)
    )
    try:
        report = run_model_check(
            client,
            max_tokens=args.max_tokens,
            models=models,
            model_source=model_source,
            protocols=protocols,
            input_cache_check=input_cache_check,
        )
    finally:
        client.close()
    report.money_id = auth.money_id
    report.money_id_created_for_run = auth.money_id_created
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
        backend = send_model_check_report(
            settings,
            html_body,
            recipients,
            f"Bitgo 大模型连通性报告 {report.generated_at.date().isoformat()}",
            list(paths.values()),
            getattr(args, "mail_backend", "auto"),
        )
        print(f"Sent {backend} report to {', '.join(recipients)}")
    return 0


def _persist_model_check_money_id(settings: Settings, args, auth: WalletAuth) -> None:
    settings.wallet_chain = auth.normalized_chain()
    settings.wallet_address = auth.wallet_address
    settings.money = auth.money
    settings.money_id = auth.money_id
    settings.signer_command = auth.signer_command
    config_path = getattr(args, "config", None) or default_config_path()
    settings.save(config_path)


def send_model_check_report(
    settings: Settings,
    html_body: str,
    recipients: list[str],
    subject: str,
    attachments: list[Path],
    backend: str = "auto",
) -> str:
    if backend not in {"auto", "agent", "gmail"}:
        raise ValueError("model-check mail backend must be auto, agent, or gmail")
    agent_available = agent_mail_available() if backend in {"auto", "agent"} else False
    use_agent_mail = backend == "agent" or (backend == "auto" and agent_available)
    if use_agent_mail:
        if backend == "agent" and not agent_available:
            raise RuntimeError("Agent Mail CLI is not available or not authorized")
        message = create_message(
            settings.mail_from,
            ", ".join(recipients),
            subject,
            "<p>Bitgo model connectivity report is ready. The complete HTML and Markdown reports are attached.</p>",
            attachments,
        )
        send_agent_message(message)
        return "Agent Mail"
    send_report_email(html_body, recipients, subject, attachments)
    return "Gmail"


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


def cmd_bff(args, settings: Settings) -> int:
    if args.page < 1:
        raise ValueError("--page must be greater than zero")
    if args.page_size < 1:
        raise ValueError("--page-size must be greater than zero")
    if args.page_size > 100:
        raise ValueError("--page-size must not exceed 100")
    if args.bff_command == "sub-wallet":
        auth = reasoning_auth(settings, args, allow_new_wallet=False)
        x_params = build_x_params(auth)
        client = BFFClient(args.base_url)
        try:
            wallet = client.get_sub_wallet(x_params)
            orders = client.get_sub_wallet_orders(
                x_params,
                page=args.page,
                page_size=args.page_size,
                user_id=args.user_id,
                category=args.category or "",
                order_type=args.order_type or "",
                start_time=args.start_time,
                end_time=args.end_time,
            )
        finally:
            client.close()
        print(
            json.dumps(
                {"wallet": wallet, "orders": orders},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.bff_command != "wallet":
        raise RuntimeError("Unknown BFF command")
    private_key = (
        args.private_key
        or os.environ.get("REASONING_PRIVATE_KEY")
        or os.environ.get(_chain_env_name(args.chain, "PRIVATE_KEY"))
        or os.environ.get("BFF_PRIVATE_KEY")
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


def reasoning_auth(
    settings: Settings,
    args=None,
    *,
    allow_new_wallet: bool = True,
    generate_missing_money_id: bool = True,
    use_wallet_profiles: bool = True,
) -> WalletAuth:
    explicit_chain = _arg_or_env(args, "chain", "REASONING_WALLET_CHAIN", "")
    requested_money_id = _arg_or_env(args, "money_id", "REASONING_MONEY_ID", "")
    chain = explicit_chain or _chain_for_money_id(settings, requested_money_id)
    chain = chain or settings.wallet_chain or _single_configured_chain(settings)
    profile_name, profile = (
        _wallet_profile(settings, chain, requested_money_id)
        if use_wallet_profiles
        else ("", None)
    )
    signer_command = _wallet_value(
        args,
        settings,
        profile,
        chain,
        "signer_command",
        "REASONING_SIGNER_COMMAND",
    )
    use_new_wallet = allow_new_wallet and _arg_bool_or_env(
        args, "new_wallet", "REASONING_NEW_WALLET"
    )
    generated = generate_wallet(chain, signer_command) if use_new_wallet else None
    private_key = (
        generated.private_key if generated else _private_key_for_chain(args, chain)
    )
    configured_money_id = _wallet_value(
        args, settings, profile, chain, "money_id", "REASONING_MONEY_ID"
    )
    money_id_created = use_new_wallet
    money_id = generate_money_id() if use_new_wallet else configured_money_id
    if not money_id:
        if not generate_missing_money_id:
            raise ValueError(
                "An existing money_id is required; provide --money-id or use "
                "--new-money-id"
            )
        money_id = generate_money_id()
        money_id_created = True
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
        wallet_profile=profile_name,
        money_id_created=money_id_created,
    )
    auth.validate()
    return auth


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
    generic_value = os.environ.get("REASONING_PRIVATE_KEY")
    if generic_value:
        return generic_value
    chain_env = _chain_env_name(chain, "PRIVATE_KEY")
    if chain_env:
        chain_value = os.environ.get(chain_env)
        if chain_value:
            return chain_value
    return ""


def _chain_for_money_id(settings: Settings, money_id: str) -> str:
    normalized_id = money_id.strip()
    if not normalized_id:
        return ""
    matches = [
        _profile_chain(name, profile)
        for name, profile in settings.wallets.items()
        if profile.money_id.strip() == normalized_id
    ]
    if settings.money_id.strip() == normalized_id and settings.wallet_chain.strip():
        matches.append(settings.wallet_chain.strip().lower())
    unique_matches = sorted(set(matches))
    if len(unique_matches) > 1:
        raise ValueError(
            f"money_id matches multiple wallet chains: {', '.join(unique_matches)}; "
            "specify --chain"
        )
    return unique_matches[0] if unique_matches else ""


def _single_configured_chain(settings: Settings) -> str:
    chains = sorted(
        _profile_chain(name, profile)
        for name, profile in settings.wallets.items()
        if profile.wallet_address and _profile_chain(name, profile)
    )
    unique_chains = sorted(set(chains))
    return unique_chains[0] if len(unique_chains) == 1 else ""


def _wallet_profile(
    settings: Settings,
    chain: str,
    requested_money_id: str = "",
) -> tuple[str, WalletProfile | None]:
    normalized = chain.strip().lower()
    if not normalized:
        return "", None
    matches = [
        (name, profile)
        for name, profile in settings.wallets.items()
        if _profile_chain(name, profile) == normalized
    ]
    if len(matches) > 1 and requested_money_id:
        money_matches = [
            (name, profile)
            for name, profile in matches
            if profile.money_id.strip() == requested_money_id.strip()
        ]
        if len(money_matches) == 1:
            return money_matches[0]
    if len(matches) > 1:
        # The current single-wallet configuration is authoritative. Legacy
        # per-chain profiles are not selected implicitly when ambiguous.
        return "", None
    return matches[0] if matches else ("", None)


def _profile_chain(name: str, profile: WalletProfile) -> str:
    return (profile.chain or name).strip().lower()


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
    requested_address = (
        getattr(args, "wallet_address", None) if args is not None else None
    )
    profile_matches_address = (
        not requested_address
        or profile is None
        or str(requested_address).strip() == profile.wallet_address.strip()
    )
    if profile is not None and profile_matches_address:
        profile_value = getattr(profile, attr)
        if profile_value:
            return str(profile_value)
    legacy_matches_address = (
        not requested_address
        or str(requested_address).strip() == settings.wallet_address.strip()
    )
    if _matches_legacy_wallet(settings, chain) and legacy_matches_address:
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
