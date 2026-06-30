from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from .crypto import WalletAuth, wallet_signed_headers
from .models import Repository, Selection


SYSTEM_PROMPT = """你是 GitHub AI 项目筛选器。只判断输入候选，不得创造仓库。
返回纯 JSON 对象，结构为 {"items":[{"full_name":"owner/repo","is_ai":true,
"category":"类别","summary_zh":"中文简介","reason_zh":"入选原因"}]}。
AI 项目包括模型、智能体、机器学习框架、推理训练工具、AI 应用和相关基础设施。
简介和原因必须简洁、基于输入事实；所有候选都必须返回一次。"""


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_response(cls, response: dict) -> "TokenUsage":
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return cls()
        input_tokens = _integer(usage.get("input_tokens", usage.get("prompt_tokens")))
        output_tokens = _integer(
            usage.get("output_tokens", usage.get("completion_tokens"))
        )
        total_tokens = _integer(usage.get("total_tokens"))
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return cls(input_tokens, output_tokens, total_tokens)

    def format(self) -> str:
        return (
            "外部推理 API token 统计："
            f"input={_display(self.input_tokens)}, "
            f"output={_display(self.output_tokens)}, "
            f"total={_display(self.total_tokens)}"
        )


class ReasoningClient:
    def __init__(self, endpoint: str, model: str, auth: WalletAuth, timeout: float = 90):
        self.endpoint = endpoint
        self.model = model
        self.auth = auth
        self.client = httpx.Client(timeout=timeout)
        self.last_usage = TokenUsage()

    def select(self, repos: list[Repository]) -> list[Selection]:
        candidates = [
            {
                "full_name": repo.full_name,
                "description": repo.description,
                "language": repo.language,
                "topics": repo.topics,
                "stars": repo.stars,
                "stars_today": repo.stars_today,
            }
            for repo in repos
        ]
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": "筛选以下 GitHub Trending 候选：\n"
                    + json.dumps(candidates, ensure_ascii=False),
                }
            ],
        }
        headers = wallet_signed_headers(self.auth)
        response = self.client.post(self.endpoint, headers=headers, json=body)
        response_data = _response_json(response)
        self.last_usage = TokenUsage.from_response(response_data)
        _raise_for_status(response, response_data)
        result = _extract_json(response_data)
        return _validate_selections(result, {repo.full_name for repo in repos})

    def test_access(self) -> dict:
        body = {
            "model": self.model,
            "max_tokens": 32,
            "messages": [
                {
                    "role": "user",
                    "content": "只回复 JSON：{\"status\":\"ok\"}",
                }
            ],
        }
        headers = wallet_signed_headers(self.auth)
        response = self.client.post(self.endpoint, headers=headers, json=body)
        response_data = _response_json(response)
        self.last_usage = TokenUsage.from_response(response_data)
        _raise_for_status(response, response_data)
        return response_data

    def close(self) -> None:
        self.client.close()


def _extract_json(response: dict) -> dict:
    content = response.get("content")
    if isinstance(content, list):
        text = "".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        text = response.get("text", "")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if text.startswith("json"):
            text = text[4:].lstrip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Reasoning API did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Reasoning API JSON root must be an object")
    return value


def _validate_selections(data: dict, allowed: set[str]) -> list[Selection]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Reasoning response must contain an items array")
    found: set[str] = set()
    selections: list[Selection] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("Each reasoning item must be an object")
        name = item.get("full_name")
        if name not in allowed or name in found:
            raise ValueError(f"Reasoning response contains unknown or duplicate repository: {name}")
        found.add(name)
        selections.append(
            Selection(
                full_name=name,
                is_ai=item.get("is_ai") is True,
                category=str(item.get("category") or "").strip(),
                summary_zh=str(item.get("summary_zh") or "").strip(),
                reason_zh=str(item.get("reason_zh") or "").strip(),
            )
        )
    if found != allowed:
        missing = ", ".join(sorted(allowed - found))
        raise ValueError(f"Reasoning response omitted repositories: {missing}")
    return selections


def _integer(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _display(value: int | None) -> str:
    return str(value) if value is not None else "服务端未提供"


def _response_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _raise_for_status(response: httpx.Response, data: dict) -> None:
    if response.is_success:
        return
    detail = data.get("error", data.get("message"))
    if isinstance(detail, dict):
        detail = detail.get("message", detail.get("type"))
    suffix = f": {str(detail)[:500]}" if detail else ""
    raise RuntimeError(
        f"Reasoning API returned HTTP {response.status_code}{suffix}"
    )
