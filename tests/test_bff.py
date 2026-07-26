import base64
import json
from types import SimpleNamespace

import httpx

from github_ai_daily.bff import BFFClient, BFFTier1Auth, build_tier1_x_params
from github_ai_daily.cli import parser


def test_build_tier1_x_params_omits_money_fields(monkeypatch):
    auth = BFFTier1Auth(
        chain="eth",
        wallet_address="0x49e4f15e31fade852bbd0eb9f5d07bbc68b01a16",
        private_key="private",
    )

    def fake_run(command, **kwargs):
        assert "--tier1" in command
        assert "--chain" in command
        assert "eth" in command
        assert "--private-key" in command
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "wallet_address": auth.wallet_address,
                    "signature": "signature",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("github_ai_daily.bff.subprocess.run", fake_run)

    x_params = build_tier1_x_params(auth)
    decoded = json.loads(base64.b64decode(x_params).decode("utf-8"))

    assert decoded == {
        "wallet_address": "0x49e4f15e31fade852bbd0eb9f5d07bbc68b01a16",
        "signature": "signature",
    }
    assert "money" not in decoded
    assert "money_id" not in decoded


def test_bff_client_fetches_wallet_transactions_and_sub_wallet_with_x_params():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if request.url.path.endswith("/sub-wallet/orders"):
            return httpx.Response(200, json={"orders": [], "total": 0})
        if request.url.path.endswith("/sub-wallet"):
            return httpx.Response(200, json={"wallet": {"subBalance": "0.23"}})
        if request.url.path.endswith("/wallet"):
            return httpx.Response(200, json={"wallet": {"balance": "1.23"}})
        return httpx.Response(200, json={"transactions": [], "total": 0})

    client = BFFClient(
        "https://bitgo.example.test", transport=httpx.MockTransport(handler)
    )
    try:
        wallet = client.get_wallet("xparams")
        transactions = client.get_transactions("xparams", page=2, page_size=50)
        sub_wallet = client.get_sub_wallet("xparams")
        orders = client.get_sub_wallet_orders(
            "xparams",
            page=3,
            page_size=25,
            category="TOKEN",
            order_type="refund",
        )
    finally:
        client.close()

    assert wallet == {"wallet": {"balance": "1.23"}}
    assert transactions == {"transactions": [], "total": 0}
    assert sub_wallet == {"wallet": {"subBalance": "0.23"}}
    assert orders == {"orders": [], "total": 0}
    assert seen_requests[0].headers["X-Params"] == "xparams"
    assert seen_requests[1].headers["X-Params"] == "xparams"
    assert seen_requests[1].url.params["page"] == "2"
    assert seen_requests[1].url.params["page_size"] == "50"
    assert seen_requests[2].url.path.endswith("/sub-wallet")
    assert seen_requests[3].url.path.endswith("/sub-wallet/orders")
    assert seen_requests[3].url.params["page"] == "3"
    assert seen_requests[3].url.params["page_size"] == "25"
    assert seen_requests[3].url.params["category"] == "TOKEN"
    assert seen_requests[3].url.params["type"] == "refund"


def test_sub_wallet_cli_reuses_existing_wallet_and_has_no_new_wallet_option():
    args = parser().parse_args(
        [
            "bff",
            "sub-wallet",
            "--chain",
            "btc",
            "--page",
            "2",
            "--type",
            "deduct",
        ]
    )

    assert args.bff_command == "sub-wallet"
    assert args.chain == "btc"
    assert args.page == 2
    assert args.order_type == "deduct"
    assert not hasattr(args, "new_wallet")
