from __future__ import annotations

import json
import re
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from .reasoning import (
    ReasoningClient,
    TokenUsage,
    _openai_chat_endpoint,
    _openai_responses_endpoint,
)


TEST_PROMPT = "你好。这个工具测试bitgo后端大模型的连通性。"
CACHE_WARMUP_PROMPT = "Reply with exactly: cache-warmup"
CACHE_READ_PROMPT = "Reply with exactly: cache-hit"
WEB_SEARCH_PROMPT = (
    "请使用联网搜索查找最近24小时的AI动态新闻，并整理成简明报告。"
    "每条新闻必须包含标题、来源、发布时间、关键事实，以及原文链接或引用。"
)
MAX_WEB_SEARCH_CONTINUATIONS = 3
WEB_SEARCH_FALLBACK_QUERY = "AI news past 24 hours"
WEB_SEARCH_URL_PATTERN = re.compile(r'https?://[^\s<>\]\[\)\}"]+')
WEB_SEARCH_FINALIZATION_INSTRUCTION = (
    "检索已完成。不要再调用任何工具；请只基于以上结果，直接输出最终中文新闻报告。"
    "每条必须包含标题、来源、发布时间、关键事实和原文 URL。"
)
# 2,048 repeated ASCII tokens provides margin above common prompt-cache minimums while
# keeping the cache scenario to exactly two Messages requests.
INPUT_CACHE_PREFIX = "cache " * 2048
MODEL_GUIDE_URL = "https://bitgo.enigmhaven.com/bitgo-product-guide-optimized-v1.html"
LOCAL_MODEL_SOURCE = "本地内置模型列表"
MODEL_CATALOG_FILENAME = "model_catalog.json"
ANTHROPIC_PROTOCOL = "Anthropic Messages"
OPENAI_PROTOCOL = "OpenAI Chat Completions"
OPENAI_RESPONSES_PROTOCOL = "OpenAI Responses"
DEFAULT_PROTOCOLS = (ANTHROPIC_PROTOCOL, OPENAI_PROTOCOL)
ALL_PROTOCOLS = (*DEFAULT_PROTOCOLS, OPENAI_RESPONSES_PROTOCOL)
PROTOCOL_NAMES = {
    "all": None,
    "messages": ANTHROPIC_PROTOCOL,
    "chat": OPENAI_PROTOCOL,
    "responses": OPENAI_RESPONSES_PROTOCOL,
}


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
    cache_stage: str = ""
    input_cache_hit: bool | None = None
    web_search_evidence: list[str] | None = None
    web_search_sources: list[str] | None = None
    web_search_candidate_sources: list[str] | None = None
    web_search_continuations: int = 0


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
    protocols: tuple[str, ...] = DEFAULT_PROTOCOLS
    input_cache_check: bool = False
    web_search_check: bool = False

    @property
    def success_count(self) -> int:
        return sum(result.ok for result in self.results)

    @property
    def model_count(self) -> int:
        return len({result.model.model_id for result in self.results})

    @property
    def fully_supported_model_count(self) -> int:
        if self.input_cache_check:
            return sum(
                len(results) == len(self.protocols) * 2
                and {result.protocol for result in results} == set(self.protocols)
                and all(result.ok for result in results)
                and all(
                    any(
                        result.protocol == protocol
                        and result.cache_stage == "read"
                        and result.input_cache_hit is True
                        for result in results
                    )
                    for protocol in self.protocols
                )
                for results in _results_by_model(self.results).values()
            )
        results_by_model = _results_by_model(self.results)
        return sum(
            len(results) == len(self.protocols)
            and {result.protocol for result in results} == set(self.protocols)
            and all(result.ok for result in results)
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
    protocols: tuple[str, ...] = DEFAULT_PROTOCOLS,
    input_cache_check: bool = False,
    web_search_check: bool = False,
) -> ModelCheckReport:
    if max_tokens < 1:
        raise ValueError("--max-tokens must be greater than zero")
    results: list[ModelCheckResult] = []
    if not models:
        raise ValueError("Model list is empty")
    if input_cache_check:
        if web_search_check:
            raise ValueError("--check-input-cache cannot be combined with --web-search")
        if len(models) != 1:
            raise ValueError("--check-input-cache requires exactly one --model")
        return _run_input_cache_check(
            client,
            models[0],
            max_tokens,
            protocols,
            now=now,
            model_source=model_source,
        )
    if web_search_check:
        if len(models) != 1:
            raise ValueError("--web-search requires exactly one --model")
        validate_web_search_protocols(protocols)
        return _run_web_search_check(
            client,
            models[0],
            max_tokens,
            protocols,
            now=now,
            model_source=model_source,
        )
    attempts = _protocol_attempts(client, protocols)
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
        protocols=protocols,
    )


def _run_input_cache_check(
    client: ReasoningClient,
    model: ModelDefinition,
    max_tokens: int,
    protocols: tuple[str, ...],
    *,
    now: datetime | None,
    model_source: str,
) -> ModelCheckReport:
    if not protocols:
        raise ValueError("At least one protocol is required")
    results: list[ModelCheckResult] = []
    scenarios = (("warmup", CACHE_WARMUP_PROMPT), ("read", CACHE_READ_PROMPT))
    total = len(protocols) * len(scenarios)
    for protocol_index, protocol in enumerate(protocols):
        # A unique, protocol-specific prefix prevents a cache entry made by
        # another run or another endpoint from satisfying this check.
        cache_prefix = f"cache-check:{protocol}:{uuid4().hex}\n{INPUT_CACHE_PREFIX}"
        prompt_cache_key = f"model-check:{uuid4().hex}"
        test_model = _cached_protocol_attempt(client, protocol)
        for stage_index, (stage, prompt) in enumerate(scenarios):
            index = protocol_index * len(scenarios) + stage_index + 1
            started_at = datetime.now().astimezone()
            started = perf_counter()
            print(
                f"[{index}/{total}] Calling {protocol} input-cache {stage}: {model.model_id}",
                flush=True,
            )
            try:
                if protocol == OPENAI_RESPONSES_PROTOCOL:
                    response = test_model(
                        model.model_id,
                        prompt,
                        max_tokens,
                        cache_prefix,
                        prompt_cache_key,
                    )
                else:
                    response = test_model(model.model_id, prompt, max_tokens, cache_prefix)
                result = _result_from_response(model, protocol, response, started_at, started)
            except httpx.TimeoutException as exc:
                result = _transport_failure(model, protocol, started_at, started, "网络/超时", str(exc))
            except httpx.HTTPError as exc:
                result = _transport_failure(model, protocol, started_at, started, "网络/超时", str(exc))
            except Exception as exc:
                result = _transport_failure(model, protocol, started_at, started, "客户端错误", str(exc))
            result.cache_stage = stage
            result.raw_request = _cached_request_body(
                protocol,
                model.model_id,
                prompt,
                max_tokens,
                cache_prefix,
                prompt_cache_key,
            )
            result.request_url = _model_request_url(client, protocol)
            if stage == "read":
                result.input_cache_hit = bool(
                    result.usage and (result.usage.cache_read_input_tokens or 0) > 0
                )
                if result.ok and not result.input_cache_hit:
                    result.ok = False
                    result.error_category = "输入缓存未命中"
                    result.error_message = (
                        "服务端未返回正数 "
                        f"{cache_hit_usage_field(protocol)}；无法确认输入缓存命中"
                    )
            results.append(result)
            print(_progress_line(index, total, result), flush=True)
    return ModelCheckReport(
        generated_at=now or datetime.now().astimezone(),
        prompt=(
            "Two-request input-cache verification: "
            + ", ".join(protocols)
        ),
        max_tokens=max_tokens,
        results=results,
        model_source=model_source,
        protocols=protocols,
        input_cache_check=True,
    )


def _run_web_search_check(
    client: ReasoningClient,
    model: ModelDefinition,
    max_tokens: int,
    protocols: tuple[str, ...],
    *,
    now: datetime | None,
    model_source: str,
) -> ModelCheckReport:
    validate_web_search_protocols(protocols)
    results: list[ModelCheckResult] = []
    for index, protocol in enumerate(protocols, start=1):
        started_at = datetime.now().astimezone()
        started = perf_counter()
        continuations = 0
        response_history: list[dict[str, Any]] = []
        raw_request = _web_search_request_body(
            protocol, model.model_id, WEB_SEARCH_PROMPT, max_tokens
        )
        print(
            f"[{index}/{len(protocols)}] Calling {protocol} web-search: {model.model_id}",
            flush=True,
        )
        try:
            if protocol == ANTHROPIC_PROTOCOL:
                response = client.test_model_with_web_search(
                    model.model_id, WEB_SEARCH_PROMPT, max_tokens
                )
                if isinstance(response.data, dict):
                    response_history.append(response.data)
                while continuations < MAX_WEB_SEARCH_CONTINUATIONS:
                    content = (response.data or {}).get("content")
                    if not isinstance(content, list):
                        break
                    if _is_web_search_tool_use(response):
                        tool_results = _execute_web_search_tool_uses(content)
                        response_history.append({"content": tool_results})
                        continuations += 1
                        response = client.continue_model_with_web_search_tool_results(
                            model.model_id,
                            WEB_SEARCH_PROMPT,
                            max_tokens,
                            content,
                            tool_results,
                        )
                    elif _is_pause_turn(response):
                        continuations += 1
                        response = client.continue_model_with_web_search(
                            model.model_id,
                            WEB_SEARCH_PROMPT,
                            max_tokens,
                            content,
                        )
                    else:
                        break
                    if isinstance(response.data, dict):
                        response_history.append(response.data)
                if _is_web_search_tool_use(response):
                    content = (response.data or {}).get("content")
                    if isinstance(content, list):
                        tool_results = _execute_web_search_tool_uses(content)
                        response_history.append({"content": tool_results})
                        continuations += 1
                        response = client.continue_model_with_web_search_tool_results(
                            model.model_id,
                            WEB_SEARCH_PROMPT,
                            max_tokens,
                            content,
                            tool_results,
                        )
                        if isinstance(response.data, dict):
                            response_history.append(response.data)
            else:
                response = client.test_model_openai_responses_with_web_search(
                    model.model_id, WEB_SEARCH_PROMPT, max_tokens
                )
                if isinstance(response.data, dict):
                    response_history.append(response.data)
            result = _result_from_response(model, protocol, response, started_at, started)
            if protocol == ANTHROPIC_PROTOCOL:
                _aggregate_web_search_usage(result, response_history)
        except httpx.TimeoutException as exc:
            result = _transport_failure(model, protocol, started_at, started, "网络/超时", str(exc))
        except httpx.HTTPError as exc:
            result = _transport_failure(model, protocol, started_at, started, "网络/超时", str(exc))
        except Exception as exc:
            result = _transport_failure(model, protocol, started_at, started, "客户端错误", str(exc))
        result.raw_request = raw_request
        result.request_url = _web_search_request_url(client, protocol)
        result.web_search_continuations = continuations
        _validate_web_search_result(result, response_history)
        results.append(result)
        print(_progress_line(index, len(protocols), result), flush=True)
    return ModelCheckReport(
        generated_at=now or datetime.now().astimezone(),
        prompt=WEB_SEARCH_PROMPT,
        max_tokens=max_tokens,
        results=results,
        model_source=model_source,
        protocols=protocols,
        web_search_check=True,
    )


def validate_web_search_protocols(protocols: tuple[str, ...]) -> None:
    if not protocols:
        raise ValueError("--web-search requires at least one protocol")
    unsupported = [protocol for protocol in protocols if protocol == OPENAI_PROTOCOL]
    if unsupported:
        raise ValueError(
            "--web-search supports only --protocol messages and/or responses; "
            "OpenAI Chat Completions does not document web_search support"
        )


def _is_pause_turn(response) -> bool:
    return (
        response.status_code < 400
        and isinstance(response.data, dict)
        and response.data.get("stop_reason") == "pause_turn"
    )


def _is_web_search_tool_use(response) -> bool:
    if response.status_code >= 400 or not isinstance(response.data, dict):
        return False
    return any(
        isinstance(item, dict)
        and item.get("type") == "tool_use"
        and item.get("name") == "web_search"
        and isinstance(item.get("id"), str)
        for item in response.data.get("content", [])
    )


def _execute_web_search_tool_uses(content: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "type": "tool_result",
            "tool_use_id": item["id"],
            "content": _web_search_tool_text(_web_search_query(item)),
        }
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "tool_use"
        and item.get("name") == "web_search"
        and isinstance(item.get("id"), str)
    ]


def _web_search_query(tool_use: dict[str, Any]) -> str:
    tool_input = tool_use.get("input")
    if isinstance(tool_input, dict):
        for key in ("query", "q", "search_query"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return WEB_SEARCH_FALLBACK_QUERY


def _web_search_tool_text(query: str) -> str:
    results, error = _run_web_search_query(query)
    if error:
        return f"Search query: {query}\nSearch failed: {error}\n\n{WEB_SEARCH_FINALIZATION_INSTRUCTION}"
    if not results:
        return f"Search query: {query}\nNo parseable results returned.\n\n{WEB_SEARCH_FINALIZATION_INSTRUCTION}"
    lines = [f"Search query: {query}", "Results:"]
    for index, result in enumerate(results[:5], start=1):
        lines.append(
            f"{index}. {result['title']}\n   URL: {result['url']}\n   Snippet: {result['snippet']}"
        )
    return "\n".join([*lines, "", WEB_SEARCH_FINALIZATION_INSTRUCTION])


def _run_web_search_query(query: str) -> tuple[list[dict[str, str]], str]:
    try:
        response = httpx.get(
            "https://www.bing.com/news/search?format=rss&q="
            + quote_plus(query)
            + "&qft=interval%3D%228%22",
            headers={"User-Agent": "Mozilla/5.0 github-ai-daily/1.0"},
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
    except (httpx.HTTPError, ElementTree.ParseError) as exc:
        return [], str(exc)
    results = []
    for item in root.findall("./channel/item")[:5]:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        snippet = (item.findtext("description") or "").strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results, ""


def _aggregate_web_search_usage(
    result: ModelCheckResult, response_history: list[dict[str, Any]]
) -> None:
    usages = [data["usage"] for data in response_history if isinstance(data.get("usage"), dict)]
    if len(usages) <= 1:
        return
    summed_keys = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "consume_amount",
    )
    aggregate: dict[str, Any] = {"calls": usages}
    for key in summed_keys:
        values = [value for usage in usages if isinstance((value := usage.get(key)), int) and not isinstance(value, bool)]
        if values:
            aggregate[key] = sum(values)
    if "input_tokens" in aggregate and "output_tokens" in aggregate:
        aggregate["total_tokens"] = aggregate["input_tokens"] + aggregate["output_tokens"]
    latest_balance = next(
        (
            usage["balance"]
            for usage in reversed(usages)
            if isinstance(usage.get("balance"), int) and not isinstance(usage["balance"], bool)
        ),
        None,
    )
    if latest_balance is not None:
        aggregate["balance"] = latest_balance
    result.usage = TokenUsage.from_response({"usage": aggregate})


def _validate_web_search_result(
    result: ModelCheckResult, response_history: list[dict[str, Any]] | None = None
) -> None:
    data = result.raw_response_json or {}
    evidence: list[str] = []
    sources: list[str] = []
    for response_data in response_history or [data]:
        found_evidence, found_sources = _web_search_evidence(result.protocol, response_data)
        evidence.extend(found_evidence)
        sources.extend(found_sources)
    result.web_search_evidence = list(dict.fromkeys(evidence))
    result.web_search_candidate_sources = _web_search_candidate_urls(
        result.protocol, response_history or [data]
    )
    local_tool_execution = "content.tool_result" in result.web_search_evidence
    if local_tool_execution:
        report_urls = _urls_in(result.response_text)
        candidates = set(result.web_search_candidate_sources)
        result.web_search_sources = [url for url in report_urls if url in candidates]
    else:
        result.web_search_sources = result.web_search_candidate_sources
    if not result.ok:
        return
    if result.protocol == ANTHROPIC_PROTOCOL and data.get("stop_reason") == "pause_turn":
        result.ok = False
        result.error_category = "联网搜索未完成"
        result.error_message = (
            f"Messages API returned pause_turn after {MAX_WEB_SEARCH_CONTINUATIONS} continuation attempts"
        )
        return
    if result.protocol == ANTHROPIC_PROTOCOL and data.get("stop_reason") == "tool_use":
        result.ok = False
        result.error_category = "联网搜索未完成"
        result.error_message = (
            "Messages API still returned tool_use after the bounded search continuations "
            "and one finalization request"
        )
        return
    if not result.response_text.strip():
        result.ok = False
        result.error_category = "联网搜索报告为空"
        result.error_message = "联网搜索调用成功，但未返回新闻报告文本"
        return
    if _is_web_search_refusal(result.response_text):
        result.ok = False
        result.error_category = "联网搜索报告不合格"
        result.error_message = "模型未生成新闻报告，而是说明无法获得可核验的新闻来源"
        return
    if not result.web_search_evidence:
        result.ok = False
        result.error_category = "未检测到联网搜索证据"
        result.error_message = "响应未包含该协议要求的 web_search 工具调用、结果或引用证据"
        return
    if local_tool_execution and not result.web_search_sources:
        result.ok = False
        result.error_category = "联网搜索来源无效"
        result.error_message = "最终报告未引用本次检索返回的可核验新闻 URL"


def _web_search_evidence(
    protocol: str, data: dict[str, Any]
) -> tuple[list[str], list[str]]:
    if protocol == ANTHROPIC_PROTOCOL:
        evidence = []
        for item in data.get("content", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "server_tool_use" and item.get("name") == "web_search":
                evidence.append("content.server_tool_use:web_search")
            if item.get("type") == "tool_use" and item.get("name") == "web_search":
                evidence.append("content.tool_use:web_search")
            if item.get("type") == "web_search_tool_result":
                evidence.append("content.web_search_tool_result")
            if item.get("type") == "tool_result":
                evidence.append("content.tool_result")
        usage = data.get("usage")
        server_tool_use = usage.get("server_tool_use") if isinstance(usage, dict) else None
        if isinstance(server_tool_use, dict) and _positive_integer(
            server_tool_use.get("web_search_requests")
        ):
            evidence.append("usage.server_tool_use.web_search_requests")
        return evidence, _urls_in(data.get("content", []))
    calls = [
        item
        for item in data.get("output", [])
        if isinstance(item, dict) and item.get("type") == "web_search_call"
    ]
    evidence = []
    sources: list[str] = []
    for call in calls:
        if call.get("results"):
            evidence.append("output.web_search_call.results")
            sources.extend(_urls_in(call.get("results")))
        action = call.get("action")
        if isinstance(action, dict) and action.get("sources"):
            evidence.append("output.web_search_call.action.sources")
            sources.extend(_urls_in(action.get("sources")))
    return evidence, list(dict.fromkeys(sources))


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_web_search_refusal(text: str) -> bool:
    normalized = text.casefold()
    return any(
        phrase in normalized
        for phrase in (
            "无法完成",
            "不能完成",
            "无法生成",
            "无有效新闻",
            "无法保证",
            "未经核实",
            "仅供参考",
            "时间异常",
            "来源可疑",
            "unable to complete",
            "cannot complete",
            "cannot generate",
        )
    )


def _unique_urls(values: list[str]) -> list[str]:
    normalized = [_normalize_url(value) for value in values]
    return list(dict.fromkeys(value for value in normalized if value))


def _web_search_candidate_urls(
    protocol: str, response_history: list[dict[str, Any]]
) -> list[str]:
    if protocol != ANTHROPIC_PROTOCOL:
        sources: list[str] = []
        for response_data in response_history:
            _, found_sources = _web_search_evidence(protocol, response_data)
            sources.extend(found_sources)
        return _unique_urls(sources)
    sources = []
    for response_data in response_history:
        content = response_data.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") not in {
                "tool_result",
                "web_search_tool_result",
            }:
                continue
            sources.extend(_urls_in(item.get("content", item)))
    return _unique_urls(sources)


def _normalize_url(value: str) -> str:
    normalized = value.strip().rstrip(".,;:!?，。；：！？")
    parsed = urlsplit(normalized)
    if parsed.hostname and parsed.hostname.casefold().endswith("bing.com") and parsed.path.casefold() == "/news/apiclick.aspx":
        target = parse_qs(parsed.query).get("url", [""])[0]
        if target:
            return _normalize_url(target)
    return normalized


def _urls_in(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url" and isinstance(item, str) and item:
                urls.append(_normalize_url(item))
            else:
                urls.extend(_urls_in(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_urls_in(item))
    elif isinstance(value, str):
        urls.extend(_normalize_url(url) for url in WEB_SEARCH_URL_PATTERN.findall(value))
    return list(dict.fromkeys(url for url in urls if url))


def _cached_protocol_attempt(client: ReasoningClient, protocol: str):
    if protocol == ANTHROPIC_PROTOCOL:
        return client.test_model_with_cached_prefix
    if protocol == OPENAI_PROTOCOL:
        return client.test_model_openai_with_cached_prefix
    if protocol == OPENAI_RESPONSES_PROTOCOL:
        return client.test_model_openai_responses_with_cached_prefix
    raise ValueError(f"Unknown protocol: {protocol}")


def cache_hit_usage_field(protocol: str) -> str:
    if protocol == OPENAI_RESPONSES_PROTOCOL:
        return "usage.input_tokens_details.cached_tokens"
    if protocol == OPENAI_PROTOCOL:
        return "usage.prompt_tokens_details.cached_tokens"
    return "usage.cache_read_input_tokens"


def select_protocols(selectors: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not selectors:
        return DEFAULT_PROTOCOLS
    requested = [
        item.strip().casefold()
        for value in selectors
        for item in value.split(",")
        if item.strip()
    ]
    if not requested:
        raise ValueError("--protocol must include at least one protocol")
    unknown = [name for name in requested if name not in PROTOCOL_NAMES]
    if unknown:
        raise ValueError(
            f"Unknown protocol: {', '.join(unknown)}. Choose from: {', '.join(PROTOCOL_NAMES)}"
        )
    if "all" in requested:
        return ALL_PROTOCOLS
    selected = {PROTOCOL_NAMES[name] for name in requested}
    return tuple(protocol for protocol in ALL_PROTOCOLS if protocol in selected)


def _protocol_attempts(client: ReasoningClient, protocols: tuple[str, ...]):
    if not protocols:
        raise ValueError("At least one protocol is required")
    attempts = []
    for protocol in protocols:
        if protocol == ANTHROPIC_PROTOCOL:
            handler = client.test_model
        elif protocol == OPENAI_PROTOCOL:
            handler = client.test_model_openai
        elif protocol == OPENAI_RESPONSES_PROTOCOL:
            handler = client.test_model_openai_responses
        else:
            raise ValueError(f"Unknown protocol: {protocol}")
        attempts.append((protocol, handler))
    return tuple(attempts)


def _results_by_model(
    results: list[ModelCheckResult],
) -> dict[str, list[ModelCheckResult]]:
    grouped: dict[str, list[ModelCheckResult]] = {}
    for result in results:
        grouped.setdefault(result.model.model_id, []).append(result)
    return grouped


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
    for selector in requested:
        normalized = selector.casefold()
        matches = [
            model
            for model in models
            if model.model_id.casefold() == normalized or model.name.casefold() == normalized
        ]
        if not matches:
            # A caller may know about a newly deployed model before the local
            # catalog is refreshed. Keep it as a provisional definition so the
            # endpoint itself can validate the model.
            matches = [
                ModelDefinition(
                    selector,
                    selector,
                    "Unknown",
                    Decimal("0"),
                    Decimal("0"),
                )
            ]
        for model in matches:
            if model.model_id not in selected_ids:
                selected.append(model)
                selected_ids.add(model.model_id)
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


def _web_search_request_body(
    protocol: str, model_id: str, prompt: str, max_tokens: int
) -> dict[str, Any]:
    if protocol == ANTHROPIC_PROTOCOL:
        return {
            "model": model_id,
            "max_tokens": max_tokens,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
            ],
        }
    if protocol == OPENAI_RESPONSES_PROTOCOL:
        return {
            "model": model_id,
            "max_output_tokens": max_tokens,
            "input": prompt,
            "tools": [{"type": "web_search"}],
        }
    raise ValueError(f"--web-search does not support protocol: {protocol}")


def _cached_request_body(
    protocol: str,
    model_id: str,
    prompt: str,
    max_tokens: int,
    cache_prefix: str,
    prompt_cache_key: str = "",
) -> dict[str, Any]:
    if protocol == ANTHROPIC_PROTOCOL:
        return {
            "model": model_id,
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
    if protocol == OPENAI_PROTOCOL:
        return {
            "model": model_id,
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
    if protocol == OPENAI_RESPONSES_PROTOCOL:
        return {
            "model": model_id,
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
    raise ValueError(f"Unknown protocol: {protocol}")


def _cached_messages_request_body(
    model_id: str, prompt: str, max_tokens: int, cache_prefix: str
) -> dict[str, Any]:
    """Keep the previous private helper available for Messages callers."""
    return _cached_request_body(
        ANTHROPIC_PROTOCOL, model_id, prompt, max_tokens, cache_prefix
    )


def _model_request_url(client: ReasoningClient, protocol: str) -> str:
    endpoint = str(getattr(client, "endpoint", ""))
    if not endpoint:
        return ""
    if protocol == OPENAI_PROTOCOL:
        return _openai_chat_endpoint(endpoint)
    if protocol == OPENAI_RESPONSES_PROTOCOL:
        return _openai_responses_endpoint(endpoint)
    return endpoint


def _web_search_request_url(client: ReasoningClient, protocol: str) -> str:
    endpoint = str(getattr(client, "endpoint", ""))
    if not endpoint:
        return ""
    if protocol == ANTHROPIC_PROTOCOL:
        return endpoint
    return _model_request_url(client, protocol)


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
    cache_suffix = (
        f" cache_read={_display_usage(usage.cache_read_input_tokens)}"
        if result.cache_stage == "read"
        else ""
    )
    if result.ok:
        return (
            f"[{index}/{total}] OK {result.model.model_id} "
            f"HTTP {result.status_code} {result.duration_ms}ms "
            f"input={_display_usage(usage.input_tokens)} "
            f"output={_display_usage(usage.output_tokens)}{cache_suffix}"
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
