from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric import ec

from .crypto import WalletAuth, wallet_signed_headers


DEFAULT_VPS_API_BASE_URL = "https://api-bitgo.enigmhaven.com"


@dataclass(frozen=True, slots=True)
class VPSResource:
    zone_id: str
    instance_type_id: str
    image_id: str
    display_name: str
    image_name: str
    cpu: int | None
    memory: int | None
    disk: int | None
    hourly_price: Decimal
    monthly_price: Decimal


def select_cheapest_resource(data: dict[str, Any]) -> VPSResource:
    """Choose a current sellable Linux resource without hard-coding provider IDs."""
    return select_resource(data)


def select_resource(
    data: dict[str, Any], *, instance_type_id: str = "", zone_id: str = ""
) -> VPSResource:
    """Choose a sellable Linux resource, optionally constrained to a VPS type/zone."""
    zones = data.get("zones")
    if not isinstance(zones, dict):
        raise ValueError("VPS resource response does not contain zones")
    candidates: list[VPSResource] = []
    wanted_type = instance_type_id.strip()
    wanted_zone = zone_id.strip()
    for candidate_zone_id, zone_data in zones.items():
        if wanted_zone and str(candidate_zone_id) != wanted_zone:
            continue
        if not isinstance(zone_data, dict):
            continue
        types = zone_data.get("instanceTypes")
        if not isinstance(types, dict):
            continue
        for type_id, type_data in types.items():
            if wanted_type and str(type_id) != wanted_type:
                continue
            if not isinstance(type_data, dict):
                continue
            instance_type = type_data.get("instanceType")
            images = type_data.get("images")
            if not isinstance(instance_type, dict) or not isinstance(images, list):
                continue
            image = _preferred_linux_image(images)
            if image is None:
                continue
            try:
                hourly = _price(instance_type.get("doPriceHourly"))
                monthly = _price(instance_type.get("doPriceMonthly"))
            except ValueError:
                continue
            image_id = str(image.get("imageId", "")).strip()
            if not image_id:
                continue
            candidates.append(
                VPSResource(
                    zone_id=str(candidate_zone_id),
                    instance_type_id=str(instance_type.get("instanceTypeId") or type_id),
                    image_id=image_id,
                    display_name=str(instance_type.get("displayName") or type_id),
                    image_name=str(image.get("displayName") or image.get("imageName") or image_id),
                    cpu=_integer(instance_type.get("cpu")),
                    memory=_integer(instance_type.get("memory")),
                    disk=_integer(instance_type.get("disk")),
                    hourly_price=hourly,
                    monthly_price=monthly,
                )
            )
    if not candidates:
        requested = []
        if wanted_type:
            requested.append(f"instanceTypeId={wanted_type}")
        if wanted_zone:
            requested.append(f"zoneId={wanted_zone}")
        suffix = f" matching {', '.join(requested)}" if requested else ""
        raise RuntimeError(f"No sellable Linux VPS resource was returned{suffix}")
    return min(
        candidates,
        key=lambda item: (
            item.hourly_price,
            item.monthly_price,
            item.cpu if item.cpu is not None else 2**31,
            item.memory if item.memory is not None else 2**31,
            item.disk if item.disk is not None else 2**31,
            item.zone_id,
            item.instance_type_id,
            item.image_id,
        ),
    )


class VPSClient:
    def __init__(
        self,
        auth: WalletAuth,
        interface_key: ec.EllipticCurvePrivateKey,
        base_url: str = DEFAULT_VPS_API_BASE_URL,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.auth = auth
        self.interface_key = interface_key
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def get_resources(self) -> dict[str, Any]:
        return self._request_json("GET", "/vps/v1/resources", signed=False)

    def list_ssh_keys(self) -> dict[str, Any]:
        return self._request_json("GET", "/vps/v1/ssh-keys")

    def create_ssh_key(
        self, display_name: str, description: str, public_key: str
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/vps/v1/ssh-keys",
            json={
                "displayName": display_name,
                "description": description,
                "publicKey": public_key,
            },
        )

    def create_vps(
        self, *, display_name: str, resource: VPSResource, ssh_key_id: str
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/vps/v1/vps",
            json={
                "displayName": display_name,
                "zoneId": resource.zone_id,
                "instanceTypeId": resource.instance_type_id,
                "imageId": resource.image_id,
                "sshKey": ssh_key_id,
            },
        )

    def get_vps(self, instance_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/vps/v1/vps/{instance_id}")

    def get_billings(
        self, *, instance_id: str, page_size: int = 20, page_num: int = 1
    ) -> dict[str, Any]:
        return self._request_json(
            "GET",
            "/vps/v1/billings",
            params={"instanceId": instance_id, "pageSize": page_size, "pageNum": page_num},
        )

    def delete_vps(self, instance_id: str) -> dict[str, Any]:
        return self._request_json("DELETE", f"/vps/v1/vps/{instance_id}")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        signed: bool = True,
    ) -> dict[str, Any]:
        headers = wallet_signed_headers(self.auth, self.interface_key) if signed else None
        response = self._client.request(method, path, headers=headers, json=json, params=params)
        response.raise_for_status()
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"VPS response for {path} must be a JSON object")
        return data


def _preferred_linux_image(images: list[Any]) -> dict[str, Any] | None:
    linux = [
        image
        for image in images
        if isinstance(image, dict)
        and str(image.get("osType", "")).strip().casefold() == "linux"
        and str(image.get("imageId", "")).strip()
    ]
    if not linux:
        return None

    def key(image: dict[str, Any]) -> tuple[int, str]:
        label = " ".join(
            str(image.get(name, "")) for name in ("category", "displayName", "imageName")
        ).casefold()
        rank = 0 if "ubuntu" in label and "lts" in label else 1 if "debian" in label else 2
        return rank, str(image.get("imageId"))

    return min(linux, key=key)


def _price(value: Any) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid VPS price: {value!r}") from exc
    if price < 0:
        raise ValueError(f"Invalid negative VPS price: {value!r}")
    return price


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
