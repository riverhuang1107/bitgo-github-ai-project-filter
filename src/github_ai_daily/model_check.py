from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .reasoning import ReasoningClient, TokenUsage, _openai_chat_endpoint, _openai_responses_endpoint


TEST_PROMPT = "你好。这个工具测试bitgo后端大模型的连通性。"
MODEL_GUIDE_URL = "https://bitgo.enigmhaven.com/bitgo-product-guide-optimized-v1.html"
LOCAL_MODEL_SOURCE = "本地内置模型列表"
MODEL_CATALOG_FILENAME = "model_catalog.json"
ANTHROPIC_PROTOCOL = "Anthropic Messages"
OPENAI_PROTOCOL = "OpenAI Chat Completions"
OPENAI_RESPONSES_PROTOCOL = "OpenAI Responses"


@dataclass(frozen=True, slots=True)
class ModelDefinition:
    model_id: str
    name: str
    provider: str
    input_price_usd_per_million: Decimal
    output_price_usd_per_million: Decimal


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    models: tuple[ModelDefinition, ...]
    source_url: str
    fetched_at: datetime


# Synced from bitgo-product-guide-optimized-v1.html, appendix "完整模型表".
MODELS: tuple[ModelDefinition, ...] = (
    ModelDefinition("deepseek-v3", "DeepSeek-V3", "DeepSeek", Decimal("0.28"), Decimal("1.11")),
    ModelDefinition("deepseek-v3.1", "DeepSeek-V3.1", "DeepSeek", Decimal("0.56"), Decimal("1.67")),
    ModelDefinition("deepseek/deepseek-v4-flash", "DeepSeek-V4-Flash", "DeepSeek", Decimal("0.14"), Decimal("0.28")),
    ModelDefinition("deepseek/deepseek-v4-pro", "DeepSeek-V4-Pro", "DeepSeek", Decimal("1.67"), Decimal("3.33")),
    ModelDefinition("deepseek/deepseek-v3.2-exp", "DeepSeek/DeepSeek-V3.2-Exp", "DeepSeek", Decimal("0.28"), Decimal("0.42")),
    ModelDefinition("deepseek/deepseek-v3.2-exp-thinking", "DeepSeek/DeepSeek-V3.2-Exp-Thinking", "DeepSeek", Decimal("0.28"), Decimal("0.42")),
    ModelDefinition("deepseek/deepseek-v3.2-251201", "Deepseek/DeepSeek-V3.2", "DeepSeek", Decimal("0.28"), Decimal("0.42")),
    ModelDefinition("claude-4.1-opus", "Claude 4.1 Opus", "Anthropic", Decimal("15"), Decimal("75.6")),
    ModelDefinition("claude-4.5-haiku", "Claude 4.5 Haiku", "Anthropic", Decimal("5"), Decimal("5.04")),
    ModelDefinition("claude-4.5-opus", "Claude 4.5 Opus", "Anthropic", Decimal("5"), Decimal("25.2")),
    ModelDefinition("claude-4.5-sonnet", "Claude 4.5 Sonnet", "Anthropic", Decimal("3"), Decimal("15.12")),
    ModelDefinition("claude-4.6-opus", "Claude 4.6 Opus", "Anthropic", Decimal("5"), Decimal("25.2")),
    ModelDefinition("claude-4.6-sonnet", "Claude 4.6 Sonnet", "Anthropic", Decimal("3"), Decimal("15.12")),
    ModelDefinition("anthropic/claude-4.7-opus", "Claude 4.7 Opus", "Anthropic", Decimal("5"), Decimal("25.2")),
    ModelDefinition("anthropic/claude-4.8-opus", "Claude 4.8 Opus", "Anthropic", Decimal("5"), Decimal("25.2")),
    ModelDefinition("MiniMax-M1", "MiniMax M1", "Minimax", Decimal("0.56"), Decimal("2.22")),
    ModelDefinition("minimax/minimax-m2.5", "Minimax/Minimax-M2.5", "Minimax", Decimal("0.29"), Decimal("1.17")),
    ModelDefinition("minimax/minimax-m2.5-highspeed", "Minimax/Minimax-M2.5 Highspeed", "Minimax", Decimal("0.58"), Decimal("2.33")),
    ModelDefinition("minimax/minimax-m2.7", "Minimax/Minimax-M2.7", "Minimax", Decimal("0.29"), Decimal("1.17")),
    ModelDefinition("minimax/minimax-m3", "Minimax/Minimax-M3", "Minimax", Decimal("0.29"), Decimal("11.67")),
    ModelDefinition("openai/gpt-5", "OpenAI/GPT-5", "OpenAI", Decimal("1.26"), Decimal("10.08")),
    ModelDefinition("openai/gpt-5-nano", "OpenAI/GPT-5 Nano", "OpenAI", Decimal("0.0504"), Decimal("0.4032")),
    ModelDefinition("openai/gpt-5.2", "OpenAI/GPT-5.2", "OpenAI", Decimal("1.764"), Decimal("14.112")),
    ModelDefinition("openai/gpt-5-mini", "Openai/GPT-5 Mini", "OpenAI", Decimal("0.252"), Decimal("2.016")),
    ModelDefinition("openai/gpt-5-pro", "Openai/GPT-5 Pro", "OpenAI", Decimal("15.12"), Decimal("120.96")),
    ModelDefinition("openai/gpt-5.2-codex", "Openai/GPT-5.2 Codex", "OpenAI", Decimal("1.764"), Decimal("14.112")),
    ModelDefinition("openai/gpt-5.3-codex", "Openai/GPT-5.3 Codex", "OpenAI", Decimal("1.764"), Decimal("14.112")),
    ModelDefinition("openai/gpt-5.4", "Openai/GPT-5.4", "OpenAI", Decimal("2.52"), Decimal("15.12")),
    ModelDefinition("openai/gpt-5.4-mini", "Openai/GPT-5.4 Mini", "OpenAI", Decimal("0.756"), Decimal("4.536")),
    ModelDefinition("openai/gpt-5.4-nano", "Openai/GPT-5.4 Nano", "OpenAI", Decimal("0.2016"), Decimal("1.26")),
    ModelDefinition("openai/gpt-5.4-pro", "Openai/GPT-5.4 Pro", "OpenAI", Decimal("30.24"), Decimal("181.44")),
    ModelDefinition("openai/gpt-5.5", "Openai/GPT-5.5", "OpenAI", Decimal("5.04"), Decimal("30.24")),
    ModelDefinition("moonshotai/kimi-k2.5", "Moonshotai/Kimi-K2.5", "Moonshot-Kimi", Decimal("0.56"), Decimal("2.92")),
    ModelDefinition("moonshotai/kimi-k2.6", "Moonshotai/Kimi-K2.6", "Moonshot-Kimi", Decimal("0.9"), Decimal("3.75")),
)


@dataclass(slots=True)
class ModelCheckResult:
    model: ModelDefinition
    started_at: datetime
    duration_ms: int
    ok: bool
    status_code: int | None = None
    response_text: str = ""
    usage: TokenUsage | None = None
    error_category: str = ""
    error_message: str = ""
    raw_error_json: dict[str, Any] | None = None
    raw_error_text: str = ""
    raw_response_json: dict[str, Any] | None = None
    request_url: str = ""
    raw_request: dict[str, Any] | None = None
    protocol: str = "Anthropic Messages"


@dataclass(slots=True)
class WalletBalance:
    retrieved_at: datetime
    money_id: str = ""
    balance: str = ""
    total_amount: str = ""
    coin_type: str = ""
    updated_at: str = ""
    error: str = ""


@dataclass(slots=True)
class ModelCheckReport:
    generated_at: datetime
    prompt: str
    max_tokens: int
    results: list[ModelCheckResult]
    model_source: str = LOCAL_MODEL_SOURCE
    money_id: str = ""
    money_id_created_for_run: bool = False
    money_id_reused_within_run: bool = True
    wallet_balance: WalletBalance | None = None

    @property
    def success_count(self) -> int:
        return sum(result.ok for result in self.results)

    @property
    def model_count(self) -> int:
        return len({result.model.model_id for result in self.results})

    @property
    def fully_supported_model_count(self) -> int:
        results_by_model: dict[str, list[ModelCheckResult]] = {}
        for result in self.results:
            results_by_model.setdefault(result.model.model_id, []).append(result)
        return sum(
            len(results) == 3 and all(result.ok for result in results)
            for results in results_by_model.values()
        )

    @property
    def failures(self) -> list[ModelCheckResult]:
        return [result for result in self.results if not result.ok]

    @property
    def input_tokens(self) -> int:
        return sum((result.usage.input_tokens or 0) for result in self.results if result.usage)

    @property
    def output_tokens(self) -> int:
        return sum((result.usage.output_tokens or 0) for result in self.results if result.usage)

    @property
    def missing_usage_count(self) -> int:
        return sum(not result.usage or not result.usage.raw for result in self.results)

    @property
    def reported_cost(self) -> Decimal:
        amounts = (_consume_amount(result.usage) for result in self.results)
        return sum((amount for amount in amounts if amount is not None), Decimal())

    @property
    def missing_cost_count(self) -> int:
        return sum(
            result.ok and _consume_amount(result.usage) is None for result in self.results
        )


def run_model_check(
    client: ReasoningClient,
    max_tokens: int = 128,
    now: datetime | None = None,
    models: tuple[ModelDefinition, ...] = MODELS,
    model_source: str = LOCAL_MODEL_SOURCE,
) -> ModelCheckReport:
    if max_tokens < 1:
        raise ValueError("--max-tokens must be greater than zero")
    results: list[ModelCheckResult] = []
    if not models:
        raise ValueError("Model list is empty")
    attempts = (
        (ANTHROPIC_PROTOCOL, client.test_model),
        (OPENAI_PROTOCOL, client.test_model_openai),
        (OPENAI_RESPONSES_PROTOCOL, client.test_model_openai_responses),
    )
    total = len(models) * len(attempts)
    for model_index, model in enumerate(models, start=1):
        for protocol_index, (protocol, test_model) in enumerate(attempts, start=1):
            index = (model_index - 1) * len(attempts) + protocol_index
            started_at = datetime.now().astimezone()
            started = perf_counter()
            raw_request = _model_request_body(
                protocol, model.model_id, TEST_PROMPT, max_tokens
            )
            request_url = _model_request_url(client, protocol)
            print(f"[{index}/{total}] Calling {protocol}: {model.model_id}", flush=True)
            try:
                response = test_model(model.model_id, TEST_PROMPT, max_tokens)
                result = _result_from_response(model, protocol, response, started_at, started)
            except httpx.TimeoutException as exc:
                result = _transport_failure(model, protocol, started_at, started, "网络/超时", str(exc))
            except httpx.HTTPError as exc:
                result = _transport_failure(model, protocol, started_at, started, "网络/超时", str(exc))
            except Exception as exc:
                result = _transport_failure(model, protocol, started_at, started, "客户端错误", str(exc))
            result.raw_request = raw_request
            result.request_url = request_url
            results.append(result)
            print(_progress_line(index, total, result), flush=True)
    return ModelCheckReport(
        generated_at=now or datetime.now().astimezone(),
        prompt=TEST_PROMPT,
        max_tokens=max_tokens,
        results=results,
        model_source=model_source,
    )


def fetch_models_from_web(url: str = MODEL_GUIDE_URL, timeout: float = 30) -> tuple[ModelDefinition, ...]:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return parse_models_from_guide_html(response.text)


def select_models(
    models: tuple[ModelDefinition, ...], selectors: list[str] | tuple[str, ...]
) -> tuple[ModelDefinition, ...]:
    requested = [
        item.strip()
        for value in selectors
        for item in value.split(",")
        if item.strip()
    ]
    if not requested:
        return models
    selected: list[ModelDefinition] = []
    selected_ids: set[str] = set()
    unknown: list[str] = []
    for selector in requested:
        normalized = selector.casefold()
        matches = [
            model
            for model in models
            if model.model_id.casefold() == normalized or model.name.casefold() == normalized
        ]
        if not matches:
            unknown.append(selector)
            continue
        for model in matches:
            if model.model_id not in selected_ids:
                selected.append(model)
                selected_ids.add(model.model_id)
    if unknown:
        raise ValueError(f"Unknown model name or ID: {', '.join(unknown)}")
    return tuple(selected)


def model_catalog_path(config_path: Path) -> Path:
    return config_path.parent / MODEL_CATALOG_FILENAME


def load_model_catalog(path: Path) -> ModelCatalog | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["models"]
        models = tuple(
            ModelDefinition(
                str(entry["model_id"]),
                str(entry["name"]),
                str(entry["provider"]),
                Decimal(str(entry["input_price_usd_per_million"])),
                Decimal(str(entry["output_price_usd_per_million"])),
            )
            for entry in entries
        )
        fetched_at = datetime.fromisoformat(str(data["fetched_at"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid local model catalog: {path}") from exc
    if not models:
        raise ValueError(f"Local model catalog is empty: {path}")
    if len({model.model_id for model in models}) != len(models):
        raise ValueError(f"Local model catalog has duplicate model IDs: {path}")
    return ModelCatalog(models, str(data.get("source_url", MODEL_GUIDE_URL)), fetched_at)


def save_model_catalog(
    path: Path,
    models: tuple[ModelDefinition, ...],
    source_url: str = MODEL_GUIDE_URL,
    now: datetime | None = None,
) -> ModelCatalog:
    if not models:
        raise ValueError("Cannot save an empty model catalog")
    catalog = ModelCatalog(models, source_url, now or datetime.now().astimezone())
    payload = {
        "schema_version": 1,
        "source_url": catalog.source_url,
        "fetched_at": catalog.fetched_at.isoformat(timespec="seconds"),
        "models": [
            {
                "model_id": model.model_id,
                "name": model.name,
                "provider": model.provider,
                "input_price_usd_per_million": str(model.input_price_usd_per_million),
                "output_price_usd_per_million": str(model.output_price_usd_per_million),
            }
            for model in catalog.models
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)
    return catalog


def parse_models_from_guide_html(document: str) -> tuple[ModelDefinition, ...]:
    appendix = BeautifulSoup(document, "html.parser").find(id="appendix")
    if appendix is None:
        raise ValueError("Bitgo product guide does not contain an appendix section")
    # The guide may put the table below an appendix heading instead of inside it.
    table = appendix.find("table") or appendix.find_next("table")
    if table is None:
        raise ValueError("Bitgo product guide appendix does not contain a model table")
    models: list[ModelDefinition] = []
    seen: set[str] = set()
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) != 5:
            continue
        model_id, name, provider, input_price, output_price = (
            cell.get_text(" ", strip=True) for cell in cells
        )
        if not model_id or model_id in seen:
            continue
        try:
            models.append(
                ModelDefinition(
                    model_id,
                    name,
                    provider,
                    Decimal(input_price.replace(",", "")),
                    Decimal(output_price.replace(",", "")),
                )
            )
        except Exception as exc:
            raise ValueError(f"Invalid model pricing row for {model_id}") from exc
        seen.add(model_id)
    if not models:
        raise ValueError("Bitgo product guide appendix model table is empty")
    return tuple(models)


def wallet_balance_from_response(
    data: dict[str, Any], retrieved_at: datetime, money_id: str = ""
) -> WalletBalance:
    wallet = _find_sub_wallet_data(data)
    if wallet is None:
        return WalletBalance(retrieved_at=retrieved_at, money_id=money_id, error="BFF 响应中未找到子钱包余额字段")
    balance = wallet.get("subBalance")
    if balance is None:
        return WalletBalance(retrieved_at=retrieved_at, money_id=money_id, error="BFF 响应中未提供 subBalance")
    return WalletBalance(
        retrieved_at=retrieved_at,
        money_id=str(wallet.get("subId") or money_id),
        balance=str(balance),
        total_amount=str(wallet.get("subTotalAmount", "")),
        coin_type=str(wallet.get("coinType", "")),
        updated_at=str(wallet.get("updatedAt", "")),
    )


def classify_error(
    status_code: int, data: dict[str, Any] | None, raw_text: str
) -> tuple[str, str]:
    detail = _error_detail(data, raw_text)
    normalized = detail.lower()
    if status_code in {401, 403}:
        return "认证失败", detail
    if status_code == 429:
        return "限流", detail
    if status_code >= 500:
        return "服务端错误", detail
    if "balance" in normalized or "insufficient" in normalized or "余额" in detail:
        return "余额不足", detail
    if "model" in normalized and any(word in normalized for word in ("invalid", "not found", "unsupported", "不存在", "不可用")):
        return "模型不可用", detail
    return f"HTTP {status_code}", detail


def _result_from_response(
    model: ModelDefinition, protocol: str, response, started_at: datetime, started: float
) -> ModelCheckResult:
    usage = TokenUsage.from_response(response.data or {})
    common = {
        "model": model,
        "started_at": started_at,
        "duration_ms": _duration_ms(started),
        "status_code": response.status_code,
        "usage": usage,
        "protocol": protocol,
        "raw_response_json": response.data,
    }
    if response.status_code >= 400:
        category, message = classify_error(response.status_code, response.data, response.text)
        return ModelCheckResult(
            **common,
            ok=False,
            error_category=category,
            error_message=message,
            raw_error_json=response.data,
            raw_error_text="" if response.data else response.text,
        )
    if not response.data:
        return ModelCheckResult(
            **common,
            ok=False,
            error_category="响应格式异常",
            error_message="接口返回的成功响应不是 JSON 对象",
            raw_error_text=response.text,
        )
    if protocol == ANTHROPIC_PROTOCOL:
        if response.data.get("content"):
            return ModelCheckResult(**common, ok=True, response_text=_content_text(response.data))
        message = "接口返回 JSON，但缺少 Anthropic 风格 content 字段"
    elif protocol == OPENAI_RESPONSES_PROTOCOL and _is_openai_responses_response(response.data):
        return ModelCheckResult(**common, ok=True, response_text=_openai_responses_content_text(response.data))
    elif _is_openai_response(response.data):
        return ModelCheckResult(**common, ok=True, response_text=_openai_content_text(response.data))
    else:
        message = "接口返回 JSON，但缺少对应协议的响应字段"
    return ModelCheckResult(
        **common,
        ok=False,
        error_category="响应格式异常",
        error_message=message,
        raw_error_json=response.data,
    )


def _transport_failure(
    model: ModelDefinition,
    protocol: str,
    started_at: datetime,
    started: float,
    category: str,
    message: str,
) -> ModelCheckResult:
    return ModelCheckResult(
        model=model,
        started_at=started_at,
        duration_ms=_duration_ms(started),
        ok=False,
        error_category=category,
        error_message=message or category,
        protocol=protocol,
    )


def _is_openai_response(data: dict[str, Any]) -> bool:
    return isinstance(data.get("choices"), list) and bool(data["choices"])


def _model_request_body(
    protocol: str, model_id: str, prompt: str, max_tokens: int
) -> dict[str, Any]:
    token_field = (
        "max_completion_tokens"
        if protocol == OPENAI_PROTOCOL
        else "max_output_tokens" if protocol == OPENAI_RESPONSES_PROTOCOL else "max_tokens"
    )
    return {
        "model": model_id,
        token_field: max_tokens,
        **({"input": prompt} if protocol == OPENAI_RESPONSES_PROTOCOL else {"messages": [{"role": "user", "content": prompt}]}),
    }


def _model_request_url(client: ReasoningClient, protocol: str) -> str:
    endpoint = str(getattr(client, "endpoint", ""))
    if not endpoint:
        return ""
    if protocol == OPENAI_PROTOCOL:
        return _openai_chat_endpoint(endpoint)
    if protocol == OPENAI_RESPONSES_PROTOCOL:
        return _openai_responses_endpoint(endpoint)
    return endpoint


def _openai_content_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "").strip()
    return str(choice.get("text") or "").strip()


def _is_openai_responses_response(data: dict[str, Any]) -> bool:
    return isinstance(data.get("output"), list) and bool(data["output"])


def _openai_responses_content_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    parts: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                parts.append(str(content.get("text") or ""))
    return "".join(parts).strip()


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _progress_line(index: int, total: int, result: ModelCheckResult) -> str:
    usage = result.usage or TokenUsage()
    if result.ok:
        return (
            f"[{index}/{total}] OK {result.model.model_id} "
            f"HTTP {result.status_code} {result.duration_ms}ms "
            f"input={_display_usage(usage.input_tokens)} "
            f"output={_display_usage(usage.output_tokens)}"
        )
    return (
        f"[{index}/{total}] FAILED {result.model.model_id} "
        f"HTTP {result.status_code if result.status_code is not None else 'n/a'} "
        f"{result.duration_ms}ms category={result.error_category} "
        f"message={result.error_message}"
    )


def _display_usage(value: int | None) -> str:
    return str(value) if value is not None else "n/a"


def _content_text(data: dict[str, Any]) -> str:
    content = data.get("content")
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    if isinstance(content, str):
        return content.strip()
    return str(data.get("text", "")).strip()


def _error_detail(data: dict[str, Any] | None, raw_text: str) -> str:
    if data:
        detail = data.get("error", data.get("message", data))
        if isinstance(detail, dict):
            detail = detail.get("message", detail.get("type", detail))
        if isinstance(detail, (dict, list)):
            return json.dumps(detail, ensure_ascii=False)
        return str(detail)
    return raw_text.strip() or "服务端未提供错误详情"


def _consume_amount(usage: TokenUsage | None) -> Decimal | None:
    if not usage or not usage.raw:
        return None
    amount = usage.raw.get("consume_amount")
    if isinstance(amount, bool):
        return None
    if isinstance(amount, (int, float, str)):
        try:
            return Decimal(str(amount)) * Decimal("0.00000001")
        except Exception:
            return None
    return None


def _find_sub_wallet_data(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if "subBalance" in value:
        return value
    for key in ("wallet", "body", "data", "subWallet"):
        found = _find_sub_wallet_data(value.get(key))
        if found is not None:
            return found
    return None
