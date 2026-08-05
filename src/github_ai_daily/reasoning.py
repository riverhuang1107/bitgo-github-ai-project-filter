from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

import httpx
from cryptography.hazmat.primitives.asymmetric import ec

from .crypto import WalletAuth, wallet_signed_headers
from .models import Repository, Selection


MIN_SELECTION_MAX_TOKENS = 4096
SELECTION_OUTPUT_TOKEN_OVERHEAD = 512
SELECTION_OUTPUT_TOKENS_PER_CANDIDATE = 256
MAX_SELECTION_MAX_TOKENS = 16384


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
    raw: dict | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None

    @classmethod
    def from_response(cls, response: dict) -> "TokenUsage":
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return cls()
        prompt_token_details = usage.get("prompt_tokens_details")
        if not isinstance(prompt_token_details, dict):
            prompt_token_details = {}
        input_token_details = usage.get("input_tokens_details")
        if not isinstance(input_token_details, dict):
            input_token_details = {}
        input_tokens = _integer(usage.get("input_tokens", usage.get("prompt_tokens")))
        output_tokens = _integer(
            usage.get("output_tokens", usage.get("completion_tokens"))
        )
        total_tokens = _integer(usage.get("total_tokens"))
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return cls(
            input_tokens,
            output_tokens,
            total_tokens,
            dict(usage),
            _integer(
                usage.get(
                    "cache_creation_input_tokens",
                    prompt_token_details.get("cache_creation_tokens"),
                )
            ),
            _integer(
                usage.get("cache_read_input_tokens")
                if usage.get("cache_read_input_tokens") is not None
                else input_token_details.get(
                    "cached_tokens", prompt_token_details.get("cached_tokens")
                )
            ),
        )

    def format(self) -> str:
        return (
            "外部推理 API token 统计："
            f"input={_display(self.input_tokens)}, "
            f"output={_display(self.output_tokens)}, "
            f"total={_display(self.total_tokens)}"
        )

    def format_json(self) -> str:
        return json.dumps({"usage": self.raw}, ensure_ascii=False, indent=2)


@dataclass(slots=True)
class ReasoningResponse:
    status_code: int
    data: dict | None
    text: str


@dataclass(slots=True)
class ReasoningCall:
    protocol: str
    model: str
    status_code: int | None
    duration_ms: int
    data: dict | None = None
    text: str = ""


class ReasoningClient:
    def __init__(
        self,
        endpoint: str,
        model: str,
        auth: WalletAuth,
        interface_key: ec.EllipticCurvePrivateKey,
        timeout: float = 180,
    ):
        self.endpoint = endpoint
        self.model = model
        self.auth = auth
        self.interface_key = interface_key
        self.client = httpx.Client(timeout=timeout)
        self.last_usage = TokenUsage()
        self.last_call: ReasoningCall | None = None

    def selection_request(self, repos: list[Repository]) -> dict:
        """Build the exact JSON body used by the project-selection request."""
        candidates = [
            {
                "full_name": repo.full_name,
                "description": repo.description,
                "language": repo.language,
                "topics": repo.topics,
                "stars": repo.stars,
                "stars_today": repo.stars_today,
                "source": repo.source,
            }
            for repo in repos
        ]
        body = {
            "model": self.model,
            "max_tokens": _selection_max_tokens(len(repos)),
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": "筛选以下今日收集的 GitHub 项目候选：\n"
                    + json.dumps(candidates, ensure_ascii=False),
                }
            ],
        }
        if _is_deepseek_v4(self.model):
            # V4 enables thinking by default. It can consume the entire output
            # budget before it emits the final structured selection.
            body["thinking"] = {"type": "disabled"}
        return body

    def select(
        self, repos: list[Repository], request_body: dict | None = None
    ) -> list[Selection]:
        body = request_body or self.selection_request(repos)
        headers = wallet_signed_headers(self.auth, self.interface_key)
        started = perf_counter()
        try:
            response = self.client.post(self.endpoint, headers=headers, json=body)
        except httpx.HTTPError:
            self.last_call = ReasoningCall(
                protocol="Anthropic Messages",
                model=self.model,
                status_code=None,
                duration_ms=_duration_ms(started),
            )
            raise
        response_data = _response_json(response)
        self.last_usage = TokenUsage.from_response(response_data)
        self.last_call = ReasoningCall(
            protocol="Anthropic Messages",
            model=self.model,
            status_code=response.status_code,
            duration_ms=_duration_ms(started),
            data=response_data,
            text=response.text,
        )
        _raise_for_status(response, response_data)
        result = _extract_json(response_data)
        return _validate_selections(result, {repo.full_name for repo in repos}, strict=False)

    def test_access(self) -> dict:
        response = self.test_model(
            self.model, "只回复 JSON：{\"status\":\"ok\"}", max_tokens=32
        )
        data = response.data or {}
        _raise_for_status_from_response(response.status_code, data)
        return data

    def test_model(self, model: str, prompt: str, max_tokens: int) -> ReasoningResponse:
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        return self._test_request(self.endpoint, body)

    def test_model_with_cached_prefix(
        self, model: str, prompt: str, max_tokens: int, cache_prefix: str
    ) -> ReasoningResponse:
        """Call the Messages API with an Anthropic ephemeral cache breakpoint."""
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {
                    "type": "text",
                    "text": cache_prefix,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": prompt}],
        }
        return self._test_request(self.endpoint, body)

    def test_model_openai_with_cached_prefix(
        self, model: str, prompt: str, max_tokens: int, cache_prefix: str
    ) -> ReasoningResponse:
        """Call Chat Completions with Modelink's Anthropic cache-control extension."""
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": cache_prefix,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
                {"role": "user", "content": prompt},
            ],
        }
        return self._test_request(_openai_chat_endpoint(self.endpoint), body)

    def test_model_openai_responses_with_cached_prefix(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        cache_prefix: str,
        prompt_cache_key: str,
    ) -> ReasoningResponse:
        """Call Responses with its native cache key and a repeated input prefix."""
        body = {
            "model": model,
            "max_output_tokens": max_tokens,
            "prompt_cache_key": prompt_cache_key,
            "prompt_cache_retention": "in_memory",
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": cache_prefix}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            ],
        }
        return self._test_request(_openai_responses_endpoint(self.endpoint), body)

    def test_model_openai(
        self, model: str, prompt: str, max_tokens: int
    ) -> ReasoningResponse:
        body = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        return self._test_request(_openai_chat_endpoint(self.endpoint), body)

    def test_model_openai_responses(
        self, model: str, prompt: str, max_tokens: int
    ) -> ReasoningResponse:
        body = {
            "model": model,
            "max_output_tokens": max_tokens,
            "input": prompt,
        }
        return self._test_request(_openai_responses_endpoint(self.endpoint), body)

    def _test_request(self, endpoint: str, body: dict) -> ReasoningResponse:
        headers = wallet_signed_headers(self.auth, self.interface_key)
        response = self.client.post(endpoint, headers=headers, json=body)
        try:
            decoded = response.json()
        except ValueError:
            decoded = None
        data = decoded if isinstance(decoded, dict) else None
        self.last_usage = TokenUsage.from_response(data or {})
        return ReasoningResponse(response.status_code, data, response.text)

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


def _is_deepseek_v4(model: str) -> bool:
    normalized = model.strip().casefold().rsplit("/", 1)[-1]
    return normalized in {"deepseek-v4-flash", "deepseek-v4-pro"}


def _selection_max_tokens(candidate_count: int) -> int:
    """Reserve enough output for every candidate's structured result."""
    requested = (
        SELECTION_OUTPUT_TOKEN_OVERHEAD
        + max(candidate_count, 0) * SELECTION_OUTPUT_TOKENS_PER_CANDIDATE
    )
    return min(MAX_SELECTION_MAX_TOKENS, max(MIN_SELECTION_MAX_TOKENS, requested))


def _validate_selections(
    data: dict, allowed: set[str], strict: bool = True
) -> list[Selection]:
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
            if strict:
                raise ValueError(f"Reasoning response contains unknown or duplicate repository: {name}")
            continue
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
        if not strict:
            return selections
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


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _response_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _raise_for_status(response: httpx.Response, data: dict) -> None:
    _raise_for_status_from_response(response.status_code, data)


def _raise_for_status_from_response(status_code: int, data: dict) -> None:
    if 200 <= status_code < 300:
        return
    detail = data.get("error", data.get("message"))
    if isinstance(detail, dict):
        detail = detail.get("message", detail.get("type"))
    suffix = f": {str(detail)[:500]}" if detail else ""
    raise RuntimeError(
        f"Reasoning API returned HTTP {status_code}{suffix}"
    )


def _openai_chat_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    suffix = "/messages"
    if not parsed.path.rstrip("/").endswith(suffix):
        raise ValueError("OpenAI compatibility requires an endpoint ending in /messages")
    path = parsed.path.rstrip("/")[: -len(suffix)] + "/chat/completions"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _openai_responses_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    suffix = "/messages"
    if not parsed.path.rstrip("/").endswith(suffix):
        raise ValueError("OpenAI compatibility requires an endpoint ending in /messages")
    path = "/bypass/openai/v1/responses"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
