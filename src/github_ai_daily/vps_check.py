from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import monotonic, sleep
from typing import Any, Callable
from uuid import uuid4

from .model_check import WalletBalance
from .vps import VPSClient, VPSResource, select_resource


RUNNING_STATUS = "InstanceStatusRunning"


@dataclass(slots=True)
class VPSBilling:
    instance_id: str
    instance_name: str
    charge: Decimal
    created_at: str = ""


@dataclass(slots=True)
class VPSCheckReport:
    generated_at: datetime
    resource: VPSResource | None = None
    ssh_key_id: str = ""
    ssh_key_created: bool = False
    instance_id: str = ""
    instance_name: str = ""
    instance_status: str = ""
    status_polls: int = 0
    billing_polls: int = 0
    billing: list[VPSBilling] = field(default_factory=list)
    wallet_balance: WalletBalance | None = None
    vps_orders: list[dict[str, str]] = field(default_factory=list)
    error: str = ""

    @property
    def billed_amount(self) -> Decimal:
        return max((item.charge for item in self.billing), default=Decimal())

    @property
    def ok(self) -> bool:
        return bool(
            not self.error
            and self.instance_id
            and self.instance_status == RUNNING_STATUS
            and self.billed_amount > 0
        )


def run_vps_check(
    client: VPSClient,
    *,
    ssh_key_id: str = "",
    ssh_public_key: str = "",
    ssh_key_display_name: str = "bitgo-vps-check",
    instance_type_id: str = "",
    zone_id: str = "",
    timeout_seconds: float = 600,
    poll_interval_seconds: float = 5,
    now: datetime | None = None,
    sleeper: Callable[[float], None] = sleep,
    clock: Callable[[], float] = monotonic,
) -> VPSCheckReport:
    report = VPSCheckReport(generated_at=now or datetime.now().astimezone())
    try:
        report.resource = select_resource(
            client.get_resources(),
            instance_type_id=instance_type_id,
            zone_id=zone_id,
        )
        report.ssh_key_id, report.ssh_key_created = _resolve_ssh_key(
            client, ssh_key_id, ssh_public_key, ssh_key_display_name
        )
        report.instance_name = f"bitgo-vps-check-{uuid4().hex[:12]}"
        created = client.create_vps(
            display_name=report.instance_name,
            resource=report.resource,
            ssh_key_id=report.ssh_key_id,
        )
        report.instance_id = _instance_id(created)
        if not report.instance_id:
            raise RuntimeError("VPS create response did not include instanceId")
        deadline = clock() + max(timeout_seconds, 0)
        report.instance_status, report.status_polls = _poll_until_running(
            client, report.instance_id, deadline, poll_interval_seconds, sleeper, clock
        )
        if report.instance_status != RUNNING_STATUS:
            raise RuntimeError(
                f"VPS did not reach {RUNNING_STATUS} before the timeout; "
                f"last status: {report.instance_status or 'unknown'}"
            )
        report.billing, report.billing_polls = _poll_until_billed(
            client, report.instance_id, deadline, poll_interval_seconds, sleeper, clock
        )
        if not any(item.charge > 0 for item in report.billing):
            raise RuntimeError("VPS billing did not report a positive charge before the timeout")
    except Exception as exc:
        report.error = str(exc)
    return report


def billing_from_response(data: dict[str, Any], instance_id: str) -> list[VPSBilling]:
    rows = data.get("instanceBilling")
    if not isinstance(rows, list):
        return []
    records: list[VPSBilling] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("instanceId", "")) != instance_id:
            continue
        charge = _decimal(row.get("charge", row.get("charges")))
        if charge is None:
            continue
        records.append(
            VPSBilling(
                instance_id=instance_id,
                instance_name=str(row.get("instanceName", "")),
                charge=charge,
                created_at=str(row.get("createdAt", "")),
            )
        )
    return records


def _resolve_ssh_key(
    client: VPSClient, ssh_key_id: str, ssh_public_key: str, display_name: str
) -> tuple[str, bool]:
    if ssh_key_id.strip():
        return ssh_key_id.strip(), False
    if not ssh_public_key.strip():
        raise ValueError(
            "An existing VPS SSH key ID or an OpenSSH public key is required; "
            "VPS SSH private keys must not be generated or stored by this tool"
        )
    response = client.create_ssh_key(
        display_name=display_name,
        description="Created by bitgo vps-check; reuse this Key ID for later checks.",
        public_key=ssh_public_key.strip(),
    )
    ssh_key = response.get("sshKey")
    if not isinstance(ssh_key, dict) or not str(ssh_key.get("sshKeyId", "")).strip():
        raise RuntimeError("SSH Key create response did not include sshKey.sshKeyId")
    return str(ssh_key["sshKeyId"]), True


def _poll_until_running(
    client: VPSClient,
    instance_id: str,
    deadline: float,
    interval: float,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> tuple[str, int]:
    polls = 0
    status = ""
    while True:
        polls += 1
        status = _instance_status(client.get_vps(instance_id))
        if status == RUNNING_STATUS or clock() >= deadline:
            return status, polls
        sleeper(max(interval, 0))


def _poll_until_billed(
    client: VPSClient,
    instance_id: str,
    deadline: float,
    interval: float,
    sleeper: Callable[[float], None],
    clock: Callable[[], float],
) -> tuple[list[VPSBilling], int]:
    polls = 0
    records: list[VPSBilling] = []
    while True:
        polls += 1
        records = billing_from_response(client.get_billings(instance_id=instance_id), instance_id)
        if any(record.charge > 0 for record in records) or clock() >= deadline:
            return records, polls
        sleeper(max(interval, 0))


def _instance_id(data: dict[str, Any]) -> str:
    return str(data.get("instanceId") or data.get("instance", {}).get("instanceId", ""))


def _instance_status(data: dict[str, Any]) -> str:
    instance = data.get("instance", data)
    return str(instance.get("status", "")) if isinstance(instance, dict) else ""


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
