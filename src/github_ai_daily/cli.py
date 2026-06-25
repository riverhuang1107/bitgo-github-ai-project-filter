from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from .config import DEFAULT_MODEL, Settings, default_config_path, user_config_dir
from .crypto import generate_private_key
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
from .reports import build_items, write_reports
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
    reasoning_test.add_argument("--key", type=Path)
    return root


def _report_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--limit", type=int, default=10)
    command.add_argument("--format", choices=["markdown", "html", "both"], default="both")
    command.add_argument("--date", help="Report date label in YYYY-MM-DD; collection is live")
    command.add_argument("--output-dir", type=Path)


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
                raise RuntimeError("Email requires HTML output; use --format html or both")
            send_existing(settings, html_path, args.to, list(paths.values()))
        return 0
    if args.command == "mail":
        return cmd_mail(args, settings)
    if args.command == "reasoning":
        return cmd_reasoning(args, settings)
    raise RuntimeError("Unknown command")


def cmd_init(args, settings: Settings) -> int:
    if not args.no_git and not Path(".git").exists():
        subprocess.run(["git", "init"], check=True)
    key_path = Path(settings.private_key_path) if settings.private_key_path else user_config_dir() / "ecdsa-private.pem"
    if not key_path.exists():
        generate_private_key(key_path)
    settings.private_key_path = str(key_path)
    settings.model = (
        os.environ.get("REASONING_API_MODEL") or settings.model or DEFAULT_MODEL
    )
    settings.mail_from = settings.mail_from or os.environ.get("GITHUB_AI_MAIL_FROM", "")
    settings.mail_test_to = settings.mail_test_to or os.environ.get("GITHUB_AI_MAIL_TEST_TO", "")
    if not settings.mail_from or not settings.mail_test_to:
        raise RuntimeError("GITHUB_AI_MAIL_FROM and GITHUB_AI_MAIL_TEST_TO are required")
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
    if not settings.model or not settings.private_key_path:
        raise RuntimeError("Tool is not initialized; run `github-ai-daily init`")
    github = GitHubClient(os.environ.get("GITHUB_TOKEN"))
    reasoning = ReasoningClient(
        settings.endpoint, settings.model, Path(settings.private_key_path)
    )
    try:
        repos = github.enrich(github.trending())
        selections = reasoning.select(repos)
    finally:
        print(reasoning.last_usage.format())
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


def send_existing(settings: Settings, html_path: Path, recipient: str, attachments: list[Path]) -> None:
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
            settings.mail_from, recipient, "GitHub AI Daily SMTP 测试", "<p>SMTP 测试成功。</p>"
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
    key_path = args.key or (
        Path(settings.private_key_path) if settings.private_key_path else None
    )
    if not model:
        raise RuntimeError("Provide --model or REASONING_API_MODEL")
    if not key_path or not key_path.exists():
        raise RuntimeError("Provide an existing ECDSA private key with --key")
    reasoning = ReasoningClient(settings.endpoint, model, key_path)
    try:
        response = reasoning.test_access()
        if not isinstance(response, dict) or not response.get("content"):
            raise RuntimeError("API responded, but no Anthropic-style content was returned")
        print("External reasoning API access: OK")
    finally:
        print(reasoning.last_usage.format())
        reasoning.close()
    return 0


def _print_paths(paths: dict[str, Path]) -> None:
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    raise SystemExit(main())
