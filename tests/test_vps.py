from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from decimal import Decimal
import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from github_ai_daily.cli import _verify_vps_primary_wallet, cmd_vps_check, cmd_vps_delete, parser
from github_ai_daily.config import Settings
from github_ai_daily.crypto import WalletAuth
from github_ai_daily.model_check import WalletBalance
from github_ai_daily.reports import render_vps_check_html, render_vps_check_markdown, write_vps_check_reports
from github_ai_daily.vps import VPSClient, VPSResource, select_cheapest_resource, select_resource
from github_ai_daily.vps_check import run_vps_check
from github_ai_daily.vps_ssh import ensure_vps_ssh_public_key


RESOURCES = {
    "zones": {
        "z-b": {
            "instanceTypes": {
                "large": {
                    "instanceType": {"instanceTypeId": "large", "cpu": 2, "memory": 4, "disk": 80, "doPriceHourly": "0.10", "doPriceMonthly": "70"},
                    "images": [{"imageId": "ubuntu2404", "displayName": "Ubuntu Server 24.04 LTS", "osType": "linux"}],
                },
                "small": {
                    "instanceType": {"instanceTypeId": "small", "cpu": 1, "memory": 1, "disk": 25, "doPriceHourly": "0.01", "doPriceMonthly": "10"},
                    "images": [
                        {"imageId": "arch", "displayName": "Arch", "osType": "linux"},
                        {"imageId": "ubuntu2204", "displayName": "Ubuntu Server 22.04 LTS", "osType": "linux"},
                    ],
                },
            }
        }
    }
}


def test_resource_selection_prefers_lowest_hourly_price_and_ubuntu_lts():
    selected = select_cheapest_resource(RESOURCES)

    assert selected.zone_id == "z-b"
    assert selected.instance_type_id == "small"
    assert selected.image_id == "ubuntu2204"
    assert selected.hourly_price == Decimal("0.01")


def test_resource_selection_accepts_requested_instance_type_and_zone():
    selected = select_resource(RESOURCES, instance_type_id="large", zone_id="z-b")
    assert selected.instance_type_id == "large"
    assert selected.zone_id == "z-b"
    with pytest.raises(RuntimeError, match="instanceTypeId=missing"):
        select_resource(RESOURCES, instance_type_id="missing")


def test_local_vps_ssh_key_is_created_once_then_reused(tmp_path):
    path = tmp_path / "vps-check-ed25519"
    public_key, created = ensure_vps_ssh_public_key(path)
    reused_public_key, reused = ensure_vps_ssh_public_key(path)

    assert created is True
    assert reused is False
    assert public_key.startswith("ssh-ed25519 ")
    assert reused_public_key == public_key
    assert "PRIVATE KEY" in path.read_text(encoding="utf-8")


def test_vps_client_uses_unsigned_resources_and_fresh_signed_headers(monkeypatch):
    seen = []
    serial = iter(("first", "second"))

    def headers(*args):
        return {"X-Params": "sensitive", "X-Nonce": next(serial), "X-Signature": "sig", "X-Public-Key": "pub"}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/resources"):
            return httpx.Response(200, json=RESOURCES)
        if request.url.path.endswith("/vps") and request.method == "POST":
            return httpx.Response(200, json={"instanceId": "instance-1"})
        return httpx.Response(200, json={})

    monkeypatch.setattr("github_ai_daily.vps.wallet_signed_headers", headers)
    auth = WalletAuth("eth", "0xwallet", "10", "money-id", "private")
    client = VPSClient(auth, ec.generate_private_key(ec.SECP256R1()), "https://vps.example.test", transport=httpx.MockTransport(handler))
    try:
        resource = select_cheapest_resource(client.get_resources())
        client.create_vps(display_name="test", resource=resource, ssh_key_id="key-1")
        client.delete_vps("instance-1")
    finally:
        client.close()

    assert "X-Params" not in seen[0].headers
    assert seen[1].headers["X-Nonce"] == "first"
    assert seen[2].headers["X-Nonce"] == "second"
    assert json.loads(seen[1].content) == {
        "displayName": "test",
        "zoneId": "z-b",
        "instanceTypeId": "small",
        "imageId": "ubuntu2204",
        "sshKey": "key-1",
    }


class FakeVPSClient:
    def __init__(self, *, billing: str = "0.01488", running: bool = True, create_error: bool = False):
        self.billing = billing
        self.running = running
        self.create_error = create_error
        self.created = []

    def get_resources(self):
        return RESOURCES

    def create_ssh_key(self, **kwargs):
        return {"sshKey": {"sshKeyId": "key-created"}}

    def create_vps(self, **kwargs):
        self.created.append(kwargs)
        if self.create_error:
            raise httpx.HTTPStatusError("bad request", request=httpx.Request("POST", "https://x"), response=httpx.Response(400))
        return {"instanceId": "instance-1"}

    def get_vps(self, instance_id):
        return {"instance": {"status": "InstanceStatusRunning" if self.running else "InstanceStatusDeploying"}}

    def get_billings(self, *, instance_id):
        return {"instanceBilling": [{"instanceId": instance_id, "instanceName": "test", "charge": self.billing, "createdAt": "2026-07-30T00:00:00Z"}]}


def test_vps_check_creates_key_and_instance_then_waits_for_positive_billing():
    report = run_vps_check(
        FakeVPSClient(),
        ssh_public_key="ssh-ed25519 AAAA test@example.com",
        timeout_seconds=0,
        poll_interval_seconds=0,
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert report.ok is True
    assert report.ssh_key_created is True
    assert report.ssh_key_id == "key-created"
    assert report.instance_id == "instance-1"
    assert report.billed_amount == Decimal("0.01488")


def test_vps_check_reports_timeout_or_missing_positive_billing_without_deleting_instance():
    report = run_vps_check(
        FakeVPSClient(billing="0"),
        ssh_key_id="existing-key",
        timeout_seconds=0,
        poll_interval_seconds=0,
    )

    assert report.instance_id == "instance-1"
    assert report.ok is False
    assert "positive charge" in report.error

    failed_create = run_vps_check(
        FakeVPSClient(create_error=True),
        ssh_key_id="existing-key",
        timeout_seconds=0,
    )
    assert failed_create.instance_id == ""
    assert "bad request" in failed_create.error


def test_primary_wallet_preflight_rejects_empty_and_requires_low_balance_confirmation(monkeypatch):
    auth = WalletAuth("eth", "0xwallet", "10", "money-id", "private")

    class EmptyClient:
        def __init__(self, *args):
            pass
        def close(self):
            pass
        def get_wallet(self, x_params):
            return {}

    monkeypatch.setattr("github_ai_daily.cli.build_tier1_x_params", lambda auth: "tier1")
    monkeypatch.setattr("github_ai_daily.cli.BFFClient", EmptyClient)
    with pytest.raises(RuntimeError, match="not found"):
        _verify_vps_primary_wallet(auth, "https://bff.example.test", False)

    class LowClient(EmptyClient):
        def get_wallet(self, x_params):
            return {"wallet": {"balance": "4.99"}}

    monkeypatch.setattr("github_ai_daily.cli.BFFClient", LowClient)
    with pytest.raises(RuntimeError, match="allow-low-balance"):
        _verify_vps_primary_wallet(auth, "https://bff.example.test", False)
    _verify_vps_primary_wallet(auth, "https://bff.example.test", True)


def test_vps_check_reuses_configured_money_id_when_no_cli_or_env_value(monkeypatch, tmp_path):
    captured = {}
    auth = WalletAuth("eth", "0xwallet", "10", "project-money-id", "private")

    def fake_reasoning_auth(settings, args, **kwargs):
        captured["money_id"] = args.money_id
        return auth

    monkeypatch.setattr("github_ai_daily.cli.reasoning_auth", fake_reasoning_auth)
    monkeypatch.setattr("github_ai_daily.cli._verify_vps_primary_wallet", lambda *args: None)
    monkeypatch.setattr("github_ai_daily.cli.reasoning_interface_key", lambda *args: object())
    monkeypatch.setattr("github_ai_daily.cli.VPSClient", lambda *args: object())
    monkeypatch.setattr(
        "github_ai_daily.cli.run_vps_check",
        lambda *args, **kwargs: type("Report", (), {"ssh_key_created": False, "wallet_balance": None, "vps_orders": [], "ok": True, "instance_id": "instance-1", "billed_amount": Decimal("0.01")})(),
    )
    monkeypatch.setattr("github_ai_daily.cli.fetch_latest_sub_wallet_balance", lambda *args: None)
    monkeypatch.setattr("github_ai_daily.cli.fetch_vps_orders", lambda *args: [])
    monkeypatch.setattr("github_ai_daily.cli.write_vps_check_reports", lambda *args: {"html": tmp_path / "report.html", "markdown": tmp_path / "report.md"})

    class Client:
        def close(self):
            pass

    monkeypatch.setattr("github_ai_daily.cli.VPSClient", lambda *args: Client())
    args = Namespace(
        timeout_seconds=0,
        poll_interval_seconds=0,
        money_id=None,
        new_money_id=False,
        save_money_id=False,
        bff_base_url="https://bff.example.test",
        allow_low_balance=False,
        ssh_key_id="key",
        ssh_public_key="",
        ssh_private_key_path=None,
        vps_api_base_url="https://vps.example.test",
        ssh_key_display_name="key",
        output_dir=tmp_path,
        send_email=False,
        config=tmp_path / "config.toml",
    )
    assert cmd_vps_check(args, Settings(money_id="project-money-id")) == 0
    assert captured["money_id"] == "project-money-id"


def test_vps_reports_redact_ssh_key_and_delete_requires_exact_confirmation(tmp_path):
    report = run_vps_check(FakeVPSClient(), ssh_key_id="secret-ssh-key-id", timeout_seconds=0)
    report.wallet_balance = WalletBalance(datetime(2026, 7, 30, tzinfo=timezone.utc), balance="12.3")
    report.vps_orders = [{"created_at": "2026-07-30", "amount": "0.01", "description": "instance-id: redacted"}]
    markdown = render_vps_check_markdown(report)
    html = render_vps_check_html(report)
    paths = write_vps_check_reports(report, tmp_path)

    assert "secret-ssh-key-id" not in markdown
    assert "Bitgo VPS 消费连通性报告" in html
    assert all(path.exists() for path in paths.values())
    parsed = parser().parse_args(["vps-check", "--allow-low-balance", "--save-money-id", "--instance-type-id", "large", "--zone-id", "z-b"])
    assert parsed.command == "vps-check"
    assert parsed.save_money_id is True
    assert parsed.instance_type_id == "large"
    assert parsed.zone_id == "z-b"
    with pytest.raises(ValueError, match="exactly match"):
        cmd_vps_delete(
            Namespace(instance_id="one", confirm_instance_id="two"), Settings()
        )
