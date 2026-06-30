from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
DEFAULT_WALLET_ADDRESS = "MTymcTbieD5u3K8Vfsa7eHN3NZuKQzwTpk"
DEFAULT_MONEY = "10"
DEFAULT_MONEY_ID = "20260630001"
DEFAULT_MODEL = "deepseek-v3"


def main() -> int:
    args = parse_args()
    private_key_wif = args.private_key_wif or os.environ.get("EXTERNAL_REASONING_LTC_WIF")
    if not private_key_wif:
        print(
            "error: provide --private-key-wif or set EXTERNAL_REASONING_LTC_WIF",
            file=sys.stderr,
        )
        return 2

    params = run_signer(
        wallet_address=args.wallet_address,
        money=args.money,
        money_id=args.money_id,
        private_key_wif=private_key_wif,
        debug=args.debug,
    )
    x_params = build_x_params(params)
    validate_x_params(x_params)

    body = {
        "messages": [{"role": "user", "content": "你好"}],
        "model": args.model,
        "stream": False,
    }

    if not args.send:
        print("dry_run=true")
        print("x_params_valid=true")
        print("wallet_address=" + params["wallet_address"])
        print("money=" + params["money"])
        print("money_id=" + params["money_id"])
        print("signature_base64_length=" + str(len(params["signature"])))
        if args.debug:
            print("message_sha256_size=" + str(params.get("message_sha256_size")))
            print("message_sha256_hex=" + str(params.get("message_sha256_hex")))
        print("request_body=" + json.dumps(body, ensure_ascii=True, separators=(",", ":")))
        print("Use --send to perform the external API request.")
        return 0

    status_code, response_text = post_reasoning_request(args.endpoint, x_params, body)
    print("status_code=" + str(status_code))
    print_usage(response_text)
    print("response=" + escape_for_console(response_text[: args.max_response_chars]))
    return 0 if 200 <= status_code < 300 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create X-Params with a Go LTC compact signature and call the reasoning API."
    )
    parser.add_argument("--wallet-address", default=DEFAULT_WALLET_ADDRESS)
    parser.add_argument("--money", default=DEFAULT_MONEY)
    parser.add_argument("--money-id", default=DEFAULT_MONEY_ID)
    parser.add_argument("--private-key-wif")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--send", action="store_true", help="send the external API request")
    parser.add_argument("--debug", action="store_true", help="print digest validation metadata")
    parser.add_argument("--max-response-chars", type=int, default=2000)
    return parser.parse_args()


def run_signer(
    *,
    wallet_address: str,
    money: str,
    money_id: str,
    private_key_wif: str,
    debug: bool,
) -> dict[str, Any]:
    script_dir = Path(__file__).resolve().parent
    command = [
        "go",
        "run",
        "./sign_ltc.go",
        "--wallet-address",
        wallet_address,
        "--money",
        money,
        "--money-id",
        money_id,
        "--private-key-wif",
        private_key_wif,
    ]
    if debug:
        command.append("--debug")

    completed = subprocess.run(
        command,
        cwd=script_dir,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or "signer failed")

    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("signer did not return valid JSON") from exc

    required = {"wallet_address", "money", "money_id", "signature"}
    missing = required - set(value)
    if missing:
        raise SystemExit("signer JSON missing fields: " + ", ".join(sorted(missing)))
    if not value["signature"]:
        raise SystemExit("signer returned an empty signature")
    return value


def build_x_params(params: dict[str, Any]) -> str:
    header_params = {
        "wallet_address": params["wallet_address"],
        "money": params["money"],
        "money_id": params["money_id"],
        "signature": params["signature"],
    }
    payload = json.dumps(header_params, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def validate_x_params(x_params: str) -> None:
    decoded = base64.b64decode(x_params, validate=True)
    value = json.loads(decoded.decode("utf-8"))
    required = {"wallet_address", "money", "money_id", "signature"}
    missing = required - set(value)
    if missing:
        raise SystemExit("X-Params JSON missing fields: " + ", ".join(sorted(missing)))


def post_reasoning_request(endpoint: str, x_params: str, body: dict[str, Any]) -> tuple[int, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Params": x_params,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def print_usage(response_text: str) -> None:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        print(json.dumps({"usage": None}, ensure_ascii=False))
        return

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        print(json.dumps({"usage": None}, ensure_ascii=False))
        return

    print(json.dumps({"usage": usage}, ensure_ascii=False, separators=(",", ":")))


def escape_for_console(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


if __name__ == "__main__":
    raise SystemExit(main())
