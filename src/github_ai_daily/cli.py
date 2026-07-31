from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

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
from .hackernews import HackerNewsClient, SOURCE_NAME as HACKER_NEWS_SOURCE_NAME
from .lobsters import LobstersClient, SOURCE_NAME as LOBSTERS_SOURCE_NAME
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
from .npm import NpmClient, SOURCE_NAME as NPM_SOURCE_NAME
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
    classify_error,
    wallet_balance_from_response,
)
from .reports import (
    build_items,
    write_model_check_reports,
    write_reasoning_request,
    write_reports,
)
from .reports import write_vps_check_reports
from .secrets import get_secret_store
from .vps import DEFAULT_VPS_API_BASE_URL, VPSClient
from .vps_check import run_vps_check
from .vps_ssh import ensure_vps_ssh_public_key


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
            "model on every selected protocol"
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

    vps_check = sub.add_parser(
        "vps-check",
        help="Create a minimal Bitgo VPS and verify its positive billing record",
    )
    vps_check.add_argument("--output-dir", type=Path, help="Directory for HTML and Markdown reports")
    vps_check.add_argument("--vps-api-base-url", default=os.environ.get("VPS_CHECK_API_BASE_URL", DEFAULT_VPS_API_BASE_URL))
    vps_check.add_argument("--bff-base-url", default=DEFAULT_BFF_BASE_URL)
    vps_check.add_argument("--ssh-key-id", help="Existing Bitgo SSH Key ID; it is reused when supplied")
    vps_check.add_argument("--ssh-public-key", help="OpenSSH public key used only when creating the reusable Bitgo SSH Key")
    vps_check.add_argument("--ssh-private-key-path", type=Path, help="Local Ed25519 SSH private key path; created when absent")
    vps_check.add_argument("--ssh-key-display-name", default="bitgo-vps-check")
    vps_check.add_argument("--instance-type-id", help="Create the specified currently sellable VPS instanceTypeId instead of the cheapest type")
    vps_check.add_argument("--zone-id", help="Optional zoneId constraint used with --instance-type-id")
    vps_check.add_argument("--timeout-seconds", type=float, default=600, help="Maximum combined status and billing polling time (default: 600)")
    vps_check.add_argument("--poll-interval-seconds", type=float, default=5, help="Polling interval in seconds (default: 5)")
    vps_check.add_argument("--allow-low-balance", action="store_true", help="Continue only after explicitly accepting a verified primary-wallet balance below USD 5")
    vps_check.add_argument("--send-email", action="store_true", help="Email the completed report")
    vps_check.add_argument("--to", help="Comma-separated report recipients")
    vps_check.add_argument("--mail-backend", choices=("auto", "agent", "gmail"), default=os.environ.get("MODEL_CHECK_MAIL_BACKEND", "auto"))
    _wallet_args(vps_check, money_id_help="Persistent money_id required for the Bitgo VPS authorization", allow_new_wallet=False)
    vps_check.add_argument("--new-money-id", action="store_true", help="Generate a new money_id after wallet preflight")
    vps_check.add_argument("--save-money-id", action="store_true", help="Confirm saving a newly created money_id as the default VPS-check wallet")
    vps_check.add_argument("--key", type=Path, help="Path to the interface ECDSA signing key")

    vps_delete = sub.add_parser("vps-delete", help="Explicitly delete a Bitgo VPS instance")
    vps_delete.add_argument("--vps-api-base-url", default=os.environ.get("VPS_CHECK_API_BASE_URL", DEFAULT_VPS_API_BASE_URL))
    vps_delete.add_argument("--instance-id", required=True)
    vps_delete.add_argument("--confirm-instance-id", required=True, help="Must exactly match --instance-id")
    _wallet_args(vps_delete, money_id_help="Existing money_id authorizing the VPS instance", allow_new_wallet=False)
    vps_delete.add_argument("--key", type=Path, help="Path to the interface ECDSA signing key")

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
        "--candidate-limit",
        type=int,
        default=10,
        help="Maximum combined candidates sent to the reasoning model (default: 10)",
    )
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
    if args.command == "vps-check":
        return cmd_vps_check(args, settings)
    if args.command == "vps-delete":
        return cmd_vps_delete(args, settings)
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
    settings.model = reasoning_model(settings)
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
    if args.candidate_limit < args.limit:
        raise ValueError("--candidate-limit must be greater than or equal to --limit")
    model = reasoning_model(settings)
    if not model:
        raise RuntimeError("Tool is not initialized; run `github-ai-daily init`")
    output_dir = args.output_dir or Path(settings.output_dir)
    github = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    external_sources = [
        (HACKER_NEWS_SOURCE_NAME, HackerNewsClient()),
        (LOBSTERS_SOURCE_NAME, LobstersClient()),
        (NPM_SOURCE_NAME, NpmClient()),
    ]
    auth = reasoning_auth(settings, args)
    _print_reasoning_wallet(auth)
    reasoning = ReasoningClient(
        reasoning_endpoint(settings), model, auth, reasoning_interface_key(settings)
    )
    try:
        github_repos = github.trending()
        candidate_groups = [github_repos]
        source_counts = [f"GitHub Trending ({len(github_repos)})"]
        for source_name, client in external_sources:
            try:
                repositories = client.trending_repositories(args.candidate_limit)
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                print(f"Warning: {source_name} is unavailable: {exc}", file=sys.stderr)
                repositories = []
            candidate_groups.append(repositories)
            source_counts.append(f"{source_name} ({len(repositories)})")
        candidates = _combine_candidate_repositories(candidate_groups, args.candidate_limit)
        repos = github.enrich(
            candidates, skip_missing=True, tolerate_rate_limit=True
        )
        if github.enrichment_warning:
            print(f"Warning: {github.enrichment_warning}", file=sys.stderr)
        print(
            f"Candidate sources: {', '.join(source_counts)}; sent to model {len(repos)}"
        )
        request_body = reasoning.selection_request(repos)
        request_path = write_reasoning_request(
            request_body, output_dir, datetime.now().astimezone()
        )
        print(f"Raw reasoning request: {request_path}", flush=True)
        print(f"Calling Messages API {model}", flush=True)
        try:
            selections = reasoning.select(repos, request_body)
        except Exception as exc:
            _print_reasoning_call_result(reasoning, exc)
            raise
        _print_reasoning_call_result(reasoning)
    finally:
        print(reasoning.last_usage.format_json())
        github.close()
        for _, client in external_sources:
            client.close()
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
    paths = write_reports(items, output_dir, args.format, generated_at)
    paths["request"] = request_path
    return paths


def _print_reasoning_call_result(
    reasoning: ReasoningClient, error: Exception | None = None
) -> None:
    call = reasoning.last_call
    model = call.model if call else reasoning.model
    duration_ms = call.duration_ms if call else 0
    status_code = call.status_code if call else None

    if error is None and status_code is not None and 200 <= status_code < 300:
        print(f"OK {model} HTTP {status_code} {duration_ms}ms", flush=True)
        return

    if status_code is None:
        category = "网络/超时" if isinstance(error, httpx.HTTPError) else "客户端错误"
        message = str(error) if error else "请求未完成"
        status = "n/a"
    elif 200 <= status_code < 300:
        category = "响应格式异常"
        message = str(error) if error else "响应校验失败"
        status = str(status_code)
    else:
        category, message = classify_error(
            status_code, call.data if call else None, call.text if call else ""
        )
        status = str(status_code)

    print(
        f"FAILED {model} HTTP {status} {duration_ms}ms "
        f"category={category} message={message}",
        flush=True,
    )


def _combine_candidate_repositories(groups, candidate_limit: int):
    """Deduplicate sources, then use a weighted rotation to keep them represented."""
    seen: set[str] = set()
    source_groups = []
    for group in groups:
        unique_group = []
        for repository in group:
            name = repository.full_name.casefold()
            if name not in seen:
                seen.add(name)
                unique_group.append(repository)
        source_groups.append(unique_group)

    candidates = []
    positions = [0] * len(source_groups)
    for index, group in enumerate(source_groups):
        if group and len(candidates) < candidate_limit:
            candidates.append(group[0])
            positions[index] = 1

    rotation = [0, 0, 0, 0, 1, 1, 2, 3]
    while len(candidates) < candidate_limit:
        added = False
        for index in rotation:
            if index >= len(source_groups) or positions[index] >= len(source_groups[index]):
                continue
            candidates.append(source_groups[index][positions[index]])
            positions[index] += 1
            added = True
            if len(candidates) == candidate_limit:
                break
        if not added:
            break
    return candidates


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


def cmd_vps_check(args, settings: Settings) -> int:
    if args.timeout_seconds < 0:
        raise ValueError("--timeout-seconds must not be negative")
    if args.poll_interval_seconds < 0:
        raise ValueError("--poll-interval-seconds must not be negative")
    requested_money_id = (
        _arg_or_env(args, "money_id", "REASONING_MONEY_ID", "")
        or settings.money_id.strip()
    )
    if args.new_money_id and requested_money_id:
        raise ValueError("--new-money-id cannot be combined with --money-id")
    if not requested_money_id and not args.new_money_id:
        raise ValueError(
            "An existing --money-id is required; explicitly pass --new-money-id after confirming the authorized amount"
        )
    if args.save_money_id and not args.new_money_id:
        raise ValueError("--save-money-id requires --new-money-id")
    # Tier1 preflight does not use money_id.  A harmless placeholder lets the
    # shared WalletAuth loader resolve the remaining wallet fields without
    # creating a zero-wallet identifier before the balance check succeeds.
    if not requested_money_id:
        args.money_id = "tier1-preflight"
    preflight_auth = reasoning_auth(
        settings,
        args,
        generate_missing_money_id=False,
        use_wallet_profiles=False,
    )
    _verify_vps_primary_wallet(preflight_auth, args.bff_base_url, args.allow_low_balance)
    generated_money_id = args.new_money_id
    args.money_id = generate_money_id() if generated_money_id else requested_money_id
    auth = reasoning_auth(
        settings,
        args,
        generate_missing_money_id=False,
        use_wallet_profiles=False,
    )
    auth.money_id_created = generated_money_id
    ssh_key_id = (
        args.ssh_key_id
        or os.environ.get("VPS_CHECK_SSH_KEY_ID", "")
        or settings.vps_ssh_key_id
    )
    ssh_public_key = args.ssh_public_key or os.environ.get("VPS_CHECK_SSH_PUBLIC_KEY", "")
    ssh_private_key_path = (
        args.ssh_private_key_path
        or (
            Path(os.environ["VPS_CHECK_SSH_PRIVATE_KEY_PATH"])
            if os.environ.get("VPS_CHECK_SSH_PRIVATE_KEY_PATH")
            else None
        )
        or (Path(settings.vps_ssh_private_key_path) if settings.vps_ssh_private_key_path else None)
        or user_config_dir() / "vps-check-ed25519"
    )
    local_ssh_key_created = False
    if not ssh_key_id and not ssh_public_key:
        ssh_public_key, local_ssh_key_created = ensure_vps_ssh_public_key(ssh_private_key_path)
    client = VPSClient(
        auth,
        reasoning_interface_key(settings, args),
        args.vps_api_base_url,
    )
    try:
        report = run_vps_check(
            client,
            ssh_key_id=ssh_key_id,
            ssh_public_key=ssh_public_key,
            ssh_key_display_name=args.ssh_key_display_name,
            instance_type_id=getattr(args, "instance_type_id", "") or "",
            zone_id=getattr(args, "zone_id", "") or "",
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
        )
    finally:
        client.close()
    if report.ssh_key_created:
        settings.vps_ssh_key_id = report.ssh_key_id
        if local_ssh_key_created:
            settings.vps_ssh_private_key_path = str(ssh_private_key_path)
        settings.save(getattr(args, "config", None) or default_config_path())
        print("Created and saved a reusable Bitgo SSH Key ID (value redacted).", flush=True)
    elif local_ssh_key_created:
        # Defensive branch for future alternate Key-resolution paths: retain the
        # location, never the private-key material itself.
        settings.vps_ssh_private_key_path = str(ssh_private_key_path)
        settings.save(getattr(args, "config", None) or default_config_path())
    if auth.money_id_created and args.save_money_id:
        _persist_model_check_money_id(settings, args, auth)
        print("New money_id saved as the default VPS-check wallet by explicit confirmation.", flush=True)
    elif auth.money_id_created:
        print("New money_id was used only for this run and was not saved as a default wallet.", flush=True)
    report.wallet_balance = fetch_latest_sub_wallet_balance(auth, args.bff_base_url)
    report.vps_orders = fetch_vps_orders(auth, args.bff_base_url)
    paths = write_vps_check_reports(report, args.output_dir or Path(settings.output_dir))
    _print_paths(paths)
    print(
        "VPS check complete: "
        f"status={'OK' if report.ok else 'FAILED'}, instance_id={report.instance_id or 'not-created'}, "
        f"billing={report.billed_amount:.8f}",
        flush=True,
    )
    if report.instance_id:
        print(
            "The VPS remains running and may continue billing. Delete it explicitly with "
            f"vps-delete --instance-id {report.instance_id} --confirm-instance-id {report.instance_id}",
            flush=True,
        )
    if args.send_email:
        recipients = parse_recipients(args.to or os.environ.get("REPORT_RECIPIENTS", ""))
        if not recipients:
            raise RuntimeError("Email recipients are required via --to or REPORT_RECIPIENTS")
        backend = send_vps_check_report(
            settings,
            paths["html"].read_text(encoding="utf-8"),
            recipients,
            f"Bitgo VPS 连通性报告 {report.generated_at.date().isoformat()}",
            list(paths.values()),
            args.mail_backend,
        )
        print(f"Sent {backend} report to {', '.join(recipients)}")
    return 0 if report.ok else 1


def cmd_vps_delete(args, settings: Settings) -> int:
    if args.instance_id != args.confirm_instance_id:
        raise ValueError("--confirm-instance-id must exactly match --instance-id")
    auth = reasoning_auth(settings, args, allow_new_wallet=False, use_wallet_profiles=False)
    client = VPSClient(auth, reasoning_interface_key(settings, args), args.vps_api_base_url)
    try:
        client.delete_vps(args.instance_id)
    finally:
        client.close()
    print("VPS deletion request accepted.")
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


def send_vps_check_report(
    settings: Settings,
    html_body: str,
    recipients: list[str],
    subject: str,
    attachments: list[Path],
    backend: str = "auto",
) -> str:
    if backend not in {"auto", "agent", "gmail"}:
        raise ValueError("vps-check mail backend must be auto, agent, or gmail")
    agent_available = agent_mail_available() if backend in {"auto", "agent"} else False
    use_agent_mail = backend == "agent" or (backend == "auto" and agent_available)
    if use_agent_mail:
        if backend == "agent" and not agent_available:
            raise RuntimeError("Agent Mail CLI is not available or not authorized")
        message = create_message(
            settings.mail_from,
            ", ".join(recipients),
            subject,
            "<p>Bitgo VPS connectivity report is ready. The complete HTML and Markdown reports are attached.</p>",
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


def fetch_vps_orders(auth: WalletAuth, base_url: str) -> list[dict[str, str]]:
    try:
        x_params = build_x_params(auth)
        client = BFFClient(base_url)
        try:
            data = client.get_sub_wallet_orders(x_params, category="VPS")
        finally:
            client.close()
    except Exception as exc:
        print(f"VPS order query unavailable: {exc}", flush=True)
        return []
    rows = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        {
            "created_at": str(row.get("createdAt", "")),
            "amount": str(row.get("amount", "")),
            "description": str(row.get("description", "")),
        }
        for row in rows
        if isinstance(row, dict)
    ]


def _verify_vps_primary_wallet(auth: WalletAuth, base_url: str, allow_low_balance: bool) -> None:
    tier1 = BFFTier1Auth(
        chain=auth.chain,
        wallet_address=auth.wallet_address,
        private_key=auth.private_key,
        signer_command=auth.signer_command,
    )
    x_params = build_tier1_x_params(tier1)
    client = BFFClient(base_url)
    try:
        data = client.get_wallet(x_params)
    finally:
        client.close()
    wallet = _find_wallet(data)
    if wallet is None:
        raise RuntimeError("Primary Bitgo wallet account was not found; recharge before creating a VPS")
    balance = _decimal_amount(wallet.get("balance"))
    if balance is None or balance <= 0:
        raise RuntimeError("Primary Bitgo wallet balance is zero or unavailable; recharge before creating a VPS")
    if balance < Decimal("5") and not allow_low_balance:
        raise RuntimeError(
            f"Primary Bitgo wallet balance is low ({balance} USD). Recharge first, or explicitly pass --allow-low-balance to continue."
        )
    print(f"Primary Bitgo wallet balance verified: {balance} USD", flush=True)


def _find_wallet(value):
    if not isinstance(value, dict):
        return None
    if "balance" in value:
        return value
    for key in ("wallet", "body", "data"):
        found = _find_wallet(value.get(key))
        if found is not None:
            return found
    return None


def _decimal_amount(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


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


def reasoning_model(settings: Settings) -> str:
    """Resolve the model consistently for every reasoning request."""
    return os.environ.get("REASONING_API_MODEL") or settings.model or DEFAULT_MODEL


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


def _print_reasoning_wallet(auth: WalletAuth) -> None:
    """Print non-secret wallet context for a reasoning-backed command."""
    print(f"Wallet address: {auth.wallet_address}")
    print(f"Money ID: {auth.money_id}")


if __name__ == "__main__":
    raise SystemExit(main())
