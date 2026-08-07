from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx

from github_ai_daily import model_check
from github_ai_daily.model_check import (
    ALL_PROTOCOLS,
    DEFAULT_PROTOCOLS,
    ModelDefinition,
    WalletBalance,
    classify_error,
    fetch_models_from_web,
    load_model_catalog,
    model_catalog_path,
    parse_models_from_guide_html,
    run_model_check,
    save_model_catalog,
    select_models,
    select_protocols,
    wallet_balance_from_response,
)
from github_ai_daily.reports import render_model_check_html, render_model_check_markdown, write_model_check_reports


def _models():
    return (
        ModelDefinition("ok", "OK", "Test", Decimal("1"), Decimal("2")),
        ModelDefinition("bad", "Bad", "Test", Decimal("1"), Decimal("2")),
        ModelDefinition("plain", "Plain", "Test", Decimal("1"), Decimal("2")),
        ModelDefinition("timeout", "Timeout", "Test", Decimal("1"), Decimal("2")),
    )


def test_model_check_records_success_and_all_failure_shapes(monkeypatch, tmp_path, capsys):
    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def test_model(self, name, prompt, max_tokens):
            assert prompt == model_check.TEST_PROMPT
            assert max_tokens == 128
            if name == "ok":
                return SimpleNamespace(
                    status_code=200,
                    data={
                        "content": [{"type": "text", "text": "hello"}],
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 4,
                            "consume_amount": 123456789,
                        },
                    },
                    text='{"content":[]}',
                )
            if name == "bad":
                return SimpleNamespace(
                    status_code=400,
                    data={"error": {"message": "invalid model"}},
                    text='{"error":{"message":"invalid model"}}',
                )
            if name == "plain":
                return SimpleNamespace(status_code=200, data=None, text="upstream unavailable")
            raise httpx.ReadTimeout("slow")

        def test_model_openai(self, name, prompt, max_tokens):
            assert prompt == model_check.TEST_PROMPT
            assert max_tokens == 128
            if name == "ok":
                return SimpleNamespace(
                    status_code=200,
                    data={
                        "choices": [{"message": {"content": "openai hello"}}],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 4,
                            "consume_amount": 123456789,
                        },
                    },
                    text='{"choices":[]}',
                )
            if name == "bad":
                return SimpleNamespace(
                    status_code=400,
                    data={"error": {"message": "invalid model"}},
                    text='{"error":{"message":"invalid model"}}',
                )
            if name == "plain":
                return SimpleNamespace(status_code=200, data=None, text="upstream unavailable")
            raise httpx.ReadTimeout("slow")

        def test_model_openai_responses(self, name, prompt, max_tokens):
            if name == "ok":
                return SimpleNamespace(status_code=200, data={"output": [{"content": [{"type": "output_text", "text": "responses hello"}]}], "usage": {"input_tokens": 10, "output_tokens": 4, "consume_amount": 123456789}}, text="{}")
            if name == "bad":
                return SimpleNamespace(status_code=400, data={"error": {"message": "invalid model"}}, text="{}")
            if name == "plain":
                return SimpleNamespace(status_code=200, data=None, text="upstream unavailable")
            raise httpx.ReadTimeout("slow")

    report = run_model_check(
        FakeClient(),
        now=datetime(2026, 7, 25, 9, 17, tzinfo=timezone.utc),
        models=_models(),
        protocols=ALL_PROTOCOLS,
    )
    terminal = capsys.readouterr().out

    assert report.model_count == 4
    assert report.success_count == 3
    assert report.fully_supported_model_count == 1
    assert report.input_tokens == 30
    assert report.output_tokens == 12
    assert report.reported_cost == Decimal("3.70370367")
    assert report.results[0].response_text == "hello"
    assert report.results[1].response_text == "openai hello"
    assert report.results[2].response_text == "responses hello"
    assert report.results[3].error_category == "模型不可用"
    assert report.results[3].raw_error_json == {"error": {"message": "invalid model"}}
    assert report.results[6].error_category == "响应格式异常"
    assert report.results[6].raw_error_text == "upstream unavailable"
    assert report.results[0].raw_request == {
        "model": "ok",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": model_check.TEST_PROMPT}],
    }
    assert report.results[1].raw_request == {
        "model": "ok",
        "max_completion_tokens": 128,
        "messages": [{"role": "user", "content": model_check.TEST_PROMPT}],
    }
    assert report.results[2].raw_request == {"model": "ok", "max_output_tokens": 128, "input": model_check.TEST_PROMPT}
    assert report.results[2].request_url == "https://api.example.test/bypass/openai/v1/responses"
    assert report.results[0].raw_response_json == {
        "content": [{"type": "text", "text": "hello"}],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 4,
            "consume_amount": 123456789,
        },
    }
    assert report.results[3].raw_response_json == {"error": {"message": "invalid model"}}
    assert report.results[6].raw_response_json is None
    assert report.results[0].request_url == "https://api.example.test/v1/messages"
    assert report.results[1].request_url == "https://api.example.test/v1/chat/completions"
    assert report.results[9].error_category == "网络/超时"
    assert "[1/12] Calling Anthropic Messages: ok" in terminal
    assert "[2/12] Calling OpenAI Chat Completions: ok" in terminal
    assert "[4/12] FAILED bad HTTP 400" in terminal
    assert "category=模型不可用" in terminal

    report.wallet_balance = WalletBalance(
        retrieved_at=datetime(2026, 7, 25, 9, 20, tzinfo=timezone.utc),
        money_id="shared-model-check-id",
        balance="12.34560000",
        total_amount="13.34560000",
        coin_type="ETH",
    )
    report.money_id = "shared-model-check-id"

    markdown = render_model_check_markdown(report)
    html = render_model_check_html(report)
    assert "失败 raw JSON" in markdown
    assert "Raw request body" in markdown
    assert "Raw request body" in html
    assert "Raw response JSON" in markdown
    assert "Raw response JSON" in html
    assert "请求 URL：https://api.example.test/v1/messages" in markdown
    assert "https://api.example.test/v1/chat/completions" in html
    assert "invalid model" in html
    assert "3.70370367" in markdown
    assert "OpenAI Chat Completions" in markdown
    assert "最新零钱包余额（USD）：12.34560000" in markdown
    assert "充值币种：ETH" in markdown
    assert "shared-model-check-id" in markdown
    assert "零钱包与授权" in html
    assert "本地内置模型列表" in markdown
    paths = write_model_check_reports(report, tmp_path)
    assert all(path.exists() for path in paths.values())


def test_error_classifier_covers_supported_categories():
    assert classify_error(401, {"error": "bad key"}, "")[0] == "认证失败"
    assert classify_error(429, {"error": "slow down"}, "")[0] == "限流"
    assert classify_error(503, {"error": "unavailable"}, "")[0] == "服务端错误"
    assert classify_error(400, {"error": "insufficient balance"}, "")[0] == "余额不足"
    assert classify_error(404, {"error": "model not found"}, "")[0] == "模型不可用"


def test_input_cache_check_uses_two_messages_requests_and_requires_a_cache_read():
    model = ModelDefinition("cache-model", "Cache Model", "Test", Decimal("1"), Decimal("2"))

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def __init__(self):
            self.calls = []

        def test_model_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix):
            self.calls.append((name, prompt, max_tokens, cache_prefix))
            usage = {
                "input_tokens": 1028,
                "output_tokens": 1,
                "cache_creation_input_tokens": 1024 if len(self.calls) == 1 else 0,
                "cache_read_input_tokens": 0 if len(self.calls) == 1 else 1024,
            }
            return SimpleNamespace(
                status_code=200,
                data={"content": [{"type": "text", "text": "ok"}], "usage": usage},
                text="{}",
            )

    client = FakeClient()
    report = run_model_check(
        client,
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        input_cache_check=True,
    )

    assert [call[1] for call in client.calls] == [
        model_check.CACHE_WARMUP_PROMPT,
        model_check.CACHE_READ_PROMPT,
    ]
    assert client.calls[0][3] == client.calls[1][3]
    assert client.calls[0][3].endswith(model_check.INPUT_CACHE_PREFIX)
    assert report.input_cache_check is True
    assert report.protocols == (model_check.ANTHROPIC_PROTOCOL,)
    assert report.success_count == 2
    assert report.fully_supported_model_count == 1
    assert report.results[0].cache_stage == "warmup"
    assert report.results[1].cache_stage == "read"
    assert report.results[1].input_cache_hit is True
    assert report.results[1].usage.cache_read_input_tokens == 1024
    assert report.results[1].raw_request["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_input_cache_check_marks_a_missing_cache_read_as_failure():
    model = ModelDefinition("cache-model", "Cache Model", "Test", Decimal("1"), Decimal("2"))

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def test_model_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix):
            return SimpleNamespace(
                status_code=200,
                data={
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 1028, "output_tokens": 1, "cache_read_input_tokens": 0},
                },
                text="{}",
            )

    report = run_model_check(
        FakeClient(),
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        input_cache_check=True,
    )

    assert report.results[1].ok is False
    assert report.results[1].input_cache_hit is False
    assert report.results[1].error_category == "输入缓存未命中"


def test_input_cache_check_runs_the_selected_protocols_with_native_request_shapes():
    model = ModelDefinition("cache-model", "Cache Model", "Test", Decimal("1"), Decimal("2"))
    calls = []

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def _response(self, protocol, prompt):
            calls.append((protocol, prompt))
            stage_is_read = prompt == model_check.CACHE_READ_PROMPT
            return SimpleNamespace(
                status_code=200,
                data={
                    "content": [{"type": "text", "text": "messages ok"}]
                    if protocol == model_check.ANTHROPIC_PROTOCOL
                    else None,
                    "choices": [{"message": {"content": "chat ok"}}]
                    if protocol == model_check.OPENAI_PROTOCOL
                    else None,
                    "output": [{"content": [{"type": "output_text", "text": "responses ok"}]}]
                    if protocol == model_check.OPENAI_RESPONSES_PROTOCOL
                    else None,
                    "usage": {
                        "input_tokens": 2050,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 1024 if stage_is_read else 0,
                    }
                    if protocol == model_check.ANTHROPIC_PROTOCOL
                    else {
                        "prompt_tokens": 2050,
                        "completion_tokens": 1,
                        "prompt_tokens_details": {
                            "cache_creation_tokens": 1024 if not stage_is_read else 0,
                            "cached_tokens": 0 if not stage_is_read else 1024,
                        },
                    }
                    if protocol == model_check.OPENAI_PROTOCOL
                    else {
                        "input_tokens": 2050,
                        "output_tokens": 1,
                        "input_tokens_details": {
                            "cached_tokens": 0 if not stage_is_read else 1024,
                        },
                    },
                },
                text="{}",
            )

        def test_model_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix):
            return self._response(model_check.ANTHROPIC_PROTOCOL, prompt)

        def test_model_openai_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix):
            return self._response(model_check.OPENAI_PROTOCOL, prompt)

        def test_model_openai_responses_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix, prompt_cache_key):
            return self._response(model_check.OPENAI_RESPONSES_PROTOCOL, prompt)

    report = run_model_check(
        FakeClient(),
        models=(model,),
        protocols=model_check.ALL_PROTOCOLS,
        input_cache_check=True,
    )

    assert len(calls) == 6
    assert [result.protocol for result in report.results] == [
        model_check.ANTHROPIC_PROTOCOL,
        model_check.ANTHROPIC_PROTOCOL,
        model_check.OPENAI_PROTOCOL,
        model_check.OPENAI_PROTOCOL,
        model_check.OPENAI_RESPONSES_PROTOCOL,
        model_check.OPENAI_RESPONSES_PROTOCOL,
    ]
    assert [result.cache_stage for result in report.results] == [
        "warmup", "read", "warmup", "read", "warmup", "read"
    ]
    assert report.protocols == model_check.ALL_PROTOCOLS
    assert report.success_count == 6
    assert report.fully_supported_model_count == 1
    assert report.results[0].raw_request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert report.results[2].raw_request["max_tokens"] == 128
    assert report.results[2].raw_request["messages"][0]["content"][0]["cache_control"] == {
        "type": "ephemeral"
    }
    assert report.results[4].raw_request["input"][0]["content"][0]["type"] == "input_text"
    assert (
        report.results[2].raw_request["messages"][0]["content"]
        == report.results[3].raw_request["messages"][0]["content"]
    )
    assert report.results[3].usage.cache_read_input_tokens == 1024
    assert report.results[4].raw_request["input"][0] == report.results[5].raw_request["input"][0]
    assert report.results[4].raw_request["prompt_cache_key"] == report.results[5].raw_request["prompt_cache_key"]
    assert report.results[4].raw_request["prompt_cache_retention"] == "in_memory"
    assert report.results[5].usage.cache_read_input_tokens == 1024
    assert "usage.input_tokens_details.cached_tokens=1024" in render_model_check_markdown(report)
    assert "usage.prompt_tokens_details.cached_tokens=1024" in render_model_check_markdown(report)


def test_input_cache_check_requires_each_selected_protocol_to_hit():
    model = ModelDefinition("cache-model", "Cache Model", "Test", Decimal("1"), Decimal("2"))

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def test_model_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix):
            return SimpleNamespace(status_code=200, data={"content": [{"type": "text", "text": "ok"}], "usage": {"cache_read_input_tokens": 1024 if prompt == model_check.CACHE_READ_PROMPT else 0}}, text="{}")

        def test_model_openai_with_cached_prefix(self, name, prompt, max_tokens, cache_prefix):
            return SimpleNamespace(
                status_code=200,
                data={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens_details": {"cached_tokens": 0}},
                },
                text="{}",
            )

    report = run_model_check(
        FakeClient(),
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL, model_check.OPENAI_PROTOCOL),
        input_cache_check=True,
    )

    assert report.success_count == 3
    assert report.results[1].input_cache_hit is True
    assert report.results[3].input_cache_hit is False
    assert report.results[3].ok is False
    assert report.fully_supported_model_count == 0


def test_web_search_check_uses_documented_messages_and_responses_shapes():
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def __init__(self):
            self.messages_calls = 0
            self.continuations = []

        def test_model_with_web_search(self, name, prompt, max_tokens):
            self.messages_calls += 1
            assert (name, prompt, max_tokens) == (
                "search-model", model_check.WEB_SEARCH_PROMPT, 128
            )
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "pause_turn",
                    "content": [{"type": "server_tool_use", "name": "web_search"}],
                    "usage": {"server_tool_use": {"web_search_requests": 1}},
                },
                text="{}",
            )

        def continue_model_with_web_search(self, name, prompt, max_tokens, content):
            self.continuations.append((name, prompt, max_tokens, content))
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "end_turn",
                    "content": [
                        {"type": "text", "text": "AI news report"},
                        {
                            "type": "web_search_tool_result",
                            "content": [{"url": "https://news.example.test/ai"}],
                        },
                    ],
                    "usage": {"server_tool_use": {"web_search_requests": 1}},
                },
                text="{}",
            )

        def test_model_openai_responses_with_web_search(self, name, prompt, max_tokens):
            assert (name, prompt, max_tokens) == (
                "search-model", model_check.WEB_SEARCH_PROMPT, 128
            )
            return SimpleNamespace(
                status_code=200,
                data={
                    "output": [
                        {
                            "type": "web_search_call",
                            "action": {"sources": [{"url": "https://source.example.test/ai"}]},
                        },
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Responses AI news report"}],
                        },
                    ],
                    "usage": {"input_tokens": 12, "output_tokens": 8},
                },
                text="{}",
            )

    client = FakeClient()
    report = run_model_check(
        client,
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL, model_check.OPENAI_RESPONSES_PROTOCOL),
        web_search_check=True,
    )

    assert report.web_search_check is True
    assert report.success_count == 2
    assert report.fully_supported_model_count == 1
    assert len(client.continuations) == 1
    assert report.results[0].web_search_continuations == 1
    assert report.results[0].web_search_sources == ["https://news.example.test/ai"]
    assert report.results[0].web_search_candidate_sources == ["https://news.example.test/ai"]
    assert report.results[1].web_search_sources == ["https://source.example.test/ai"]
    assert report.results[0].request_url == "https://api.example.test/v1/messages"
    assert report.results[1].request_url == "https://api.example.test/bypass/openai/v1/responses"
    assert report.results[0].raw_request == {
        "model": "search-model",
        "max_tokens": 128,
        "stream": False,
        "messages": [{"role": "user", "content": model_check.WEB_SEARCH_PROMPT}],
        "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
    }
    assert report.results[1].raw_request == {
        "model": "search-model",
        "max_output_tokens": 128,
        "input": model_check.WEB_SEARCH_PROMPT,
        "tools": [{"type": "web_search"}],
    }
    assert "Web search evidence" in render_model_check_markdown(report)
    assert "Web search sources" in render_model_check_html(report)


def test_web_search_check_executes_messages_tool_use_and_returns_tool_result(monkeypatch):
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))
    monkeypatch.setattr(
        model_check,
        "_run_web_search_query",
        lambda query: ([{"title": "AI headline", "url": "https://news.example.test/ai", "snippet": "details"}], ""),
    )

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def __init__(self):
            self.tool_results = []

        def test_model_with_web_search(self, name, prompt, max_tokens):
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "tool_use",
                    "content": [{"id": "tool-1", "type": "tool_use", "name": "web_search", "input": {}}],
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                },
                text="{}",
            )

        def continue_model_with_web_search_tool_results(
            self, name, prompt, max_tokens, assistant_content, tool_results
        ):
            self.tool_results = tool_results
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "end_turn",
                    "content": [
                        {
                            "type": "text",
                            "text": "AI news report: https://news.example.test/ai",
                        }
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
                text="{}",
            )

    client = FakeClient()
    report = run_model_check(
        client,
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        web_search_check=True,
    )

    assert report.success_count == 1
    assert client.tool_results == [
        {
            "type": "tool_result",
            "tool_use_id": "tool-1",
            "content": (
                "Search query: AI news past 24 hours\nResults:\n1. AI headline\n"
                "   URL: https://news.example.test/ai\n   Snippet: details\n\n"
                + model_check.WEB_SEARCH_FINALIZATION_INSTRUCTION
            ),
        }
    ]
    assert report.results[0].web_search_sources == ["https://news.example.test/ai"]
    assert report.results[0].web_search_candidate_sources == ["https://news.example.test/ai"]
    assert report.results[0].web_search_continuations == 1
    assert report.results[0].usage.input_tokens == 5
    assert report.results[0].usage.output_tokens == 3


def test_web_search_check_rejects_local_tool_result_without_cited_news_source(monkeypatch):
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))
    monkeypatch.setattr(
        model_check,
        "_run_web_search_query",
        lambda query: ([{"title": "AI headline", "url": "https://news.example.test/ai", "snippet": "details"}], ""),
    )

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        def test_model_with_web_search(self, name, prompt, max_tokens):
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "tool_use",
                    "content": [{"id": "tool-1", "type": "tool_use", "name": "web_search", "input": {}}],
                    "usage": {},
                },
                text="{}",
            )

        def continue_model_with_web_search_tool_results(self, *args):
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "无法完成这项任务，搜索结果没有新闻。"}],
                    "usage": {},
                },
                text="{}",
            )

    report = run_model_check(
        FakeClient(),
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        web_search_check=True,
    )

    assert report.results[0].ok is False
    assert report.results[0].error_category == "联网搜索报告不合格"
    assert report.results[0].web_search_sources == []
    assert report.results[0].web_search_candidate_sources == ["https://news.example.test/ai"]


def test_web_search_check_does_not_treat_final_response_urls_as_candidates():
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))
    final_response = {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Report https://model.example.test/self-citation"}],
    }
    result = model_check.ModelCheckResult(
        model=model,
        started_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        duration_ms=1,
        ok=True,
        protocol=model_check.ANTHROPIC_PROTOCOL,
        response_text="Report https://model.example.test/self-citation",
        raw_response_json=final_response,
    )

    model_check._validate_web_search_result(
        result,
        [
            {"content": [{"id": "tool-1", "type": "tool_use", "name": "web_search"}]},
            {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "URL: https://search.example.test/article",
                    }
                ]
            },
            final_response,
        ],
    )

    assert result.ok is False
    assert result.error_category == "联网搜索来源无效"
    assert result.web_search_candidate_sources == ["https://search.example.test/article"]
    assert result.web_search_sources == []


def test_web_search_refusal_detection_covers_unverified_results():
    assert model_check._is_web_search_refusal("这些结果未经核实，仅供参考，无法保证真实性。")


def test_web_search_sources_unwrap_bing_news_redirects():
    wrapped = (
        "https://www.bing.com/news/apiclick.aspx?ref=FexRss&url="
        "https%3A%2F%2Fnews.example.test%2Fai%2Fstory%3Fid%3D1"
    )

    assert model_check._unique_urls([wrapped]) == ["https://news.example.test/ai/story?id=1"]


def test_web_search_check_marks_exhausted_tool_use_as_incomplete(monkeypatch):
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))
    monkeypatch.setattr(model_check, "_run_web_search_query", lambda query: ([], ""))

    class FakeClient:
        endpoint = "https://api.example.test/v1/messages"

        @staticmethod
        def _tool_use():
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "tool_use",
                    "content": [{"id": "tool-1", "type": "tool_use", "name": "web_search", "input": {}}],
                    "usage": {},
                },
                text="{}",
            )

        def test_model_with_web_search(self, *args):
            return self._tool_use()

        def continue_model_with_web_search_tool_results(self, *args):
            return self._tool_use()

    report = run_model_check(
        FakeClient(),
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        web_search_check=True,
    )

    assert report.results[0].ok is False
    assert report.results[0].error_category == "联网搜索未完成"
    assert report.results[0].web_search_continuations == model_check.MAX_WEB_SEARCH_CONTINUATIONS + 1


def test_web_search_check_rejects_missing_evidence_and_exhausted_pause_turns():
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))

    class NoEvidenceClient:
        endpoint = "https://api.example.test/v1/messages"

        def test_model_with_web_search(self, name, prompt, max_tokens):
            return SimpleNamespace(
                status_code=200,
                data={"content": [{"type": "text", "text": "report"}], "usage": {}},
                text="{}",
            )

    missing = run_model_check(
        NoEvidenceClient(),
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        web_search_check=True,
    )
    assert missing.results[0].ok is False
    assert missing.results[0].error_category == "未检测到联网搜索证据"

    class PauseClient:
        endpoint = "https://api.example.test/v1/messages"

        def __init__(self):
            self.calls = 0

        def test_model_with_web_search(self, name, prompt, max_tokens):
            self.calls += 1
            return self._paused()

        def continue_model_with_web_search(self, name, prompt, max_tokens, content):
            self.calls += 1
            return self._paused()

        @staticmethod
        def _paused():
            return SimpleNamespace(
                status_code=200,
                data={
                    "stop_reason": "pause_turn",
                    "content": [{"type": "server_tool_use", "name": "web_search"}],
                    "usage": {"server_tool_use": {"web_search_requests": 1}},
                },
                text="{}",
            )

    client = PauseClient()
    paused = run_model_check(
        client,
        models=(model,),
        protocols=(model_check.ANTHROPIC_PROTOCOL,),
        web_search_check=True,
    )
    assert client.calls == 1 + model_check.MAX_WEB_SEARCH_CONTINUATIONS
    assert paused.results[0].ok is False
    assert paused.results[0].error_category == "联网搜索未完成"


def test_web_search_check_rejects_chat_and_conflicting_cache_mode():
    model = ModelDefinition("search-model", "Search Model", "Test", Decimal("1"), Decimal("2"))
    try:
        run_model_check(
            object(),
            models=(model,),
            protocols=(model_check.OPENAI_PROTOCOL,),
            web_search_check=True,
        )
    except ValueError as exc:
        assert "messages and/or responses" in str(exc)
    else:
        raise AssertionError("Expected web-search Chat Completions validation failure")

    try:
        run_model_check(
            object(),
            models=(model,),
            protocols=(model_check.ANTHROPIC_PROTOCOL,),
            input_cache_check=True,
            web_search_check=True,
        )
    except ValueError as exc:
        assert "cannot be combined" in str(exc)
    else:
        raise AssertionError("Expected incompatible mode validation failure")


def test_product_guide_catalog_has_all_34_models():
    assert len(model_check.MODELS) == 34
    assert model_check.MODELS[0].model_id == "deepseek-v3"
    assert model_check.MODELS[-1].model_id == "moonshotai/kimi-k2.6"


def test_product_guide_parser_reads_model_table_below_appendix_heading():
    models = parse_models_from_guide_html(
        """
        <h2 id="appendix">附录</h2>
        <table><tbody>
          <tr><td>openai/test</td><td>Test</td><td>OpenAI</td><td>1.25</td><td>2.50</td></tr>
          <tr><td>deepseek/test</td><td>Deep Test</td><td>DeepSeek</td><td>0.28</td><td>1.11</td></tr>
        </tbody></table>
        """
    )

    assert [model.model_id for model in models] == ["openai/test", "deepseek/test"]
    assert models[0].input_price_usd_per_million == Decimal("1.25")
    assert models[1].output_price_usd_per_million == Decimal("1.11")


def test_fetch_models_from_web_uses_product_guide_response(monkeypatch):
    class Response:
        text = """<section id="appendix"><table><tbody><tr><td>test</td><td>Test</td><td>Provider</td><td>1</td><td>2</td></tr></tbody></table></section>"""

        def raise_for_status(self):
            return None

    captured = {}

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(model_check.httpx, "get", fake_get)

    models = fetch_models_from_web("https://guide.example.test", timeout=12)

    assert models[0].model_id == "test"
    assert captured == {
        "url": "https://guide.example.test",
        "timeout": 12,
        "follow_redirects": True,
    }


def test_model_catalog_round_trip_is_saved_alongside_config(tmp_path):
    config_path = tmp_path / "config.toml"
    catalog_path = model_catalog_path(config_path)
    saved = save_model_catalog(
        catalog_path,
        _models()[:2],
        source_url="https://guide.example.test",
        now=datetime(2026, 7, 25, 9, 17, tzinfo=timezone.utc),
    )

    loaded = load_model_catalog(catalog_path)

    assert saved.models == _models()[:2]
    assert loaded == saved
    assert catalog_path == tmp_path / "model_catalog.json"


def test_select_models_supports_names_ids_commas_and_deduplication():
    selected = select_models(_models(), ["OK,bad", "Bad", "plain"])

    assert [model.model_id for model in selected] == ["ok", "bad", "plain"]


def test_select_models_keeps_unknown_values_for_endpoint_validation():
    selected = select_models(_models(), ["missing-model"])

    assert [model.model_id for model in selected] == ["missing-model"]
    assert selected[0].provider == "Unknown"
    assert selected[0].input_price_usd_per_million == Decimal("0")


def test_select_protocols_defaults_to_messages_and_chat_and_supports_combinations():
    assert select_protocols(None) == DEFAULT_PROTOCOLS
    assert select_protocols(["responses,messages", "chat"]) == ALL_PROTOCOLS
    assert select_protocols(["all"]) == ALL_PROTOCOLS
    assert select_protocols(["responses", "responses"]) == ("OpenAI Responses",)


def test_select_protocols_rejects_unknown_values():
    try:
        select_protocols(["messages,unknown"])
    except ValueError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("Expected an unknown protocol error")


def test_model_check_defaults_to_messages_and_chat_protocols(capsys):
    model = ModelDefinition("openai/test", "OpenAI Test", "OpenAI", Decimal("1"), Decimal("2"))

    class FakeClient:
        def test_model(self, name, prompt, max_tokens):
            return SimpleNamespace(status_code=200, data={"content": [], "usage": {}}, text="{}")

        def test_model_openai(self, name, prompt, max_tokens):
            assert name == "openai/test"
            return SimpleNamespace(
                status_code=200,
                data={"choices": [{"message": {"content": "hello"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
                text="{}",
            )

    report = run_model_check(FakeClient(), models=(model,))

    assert report.success_count == 1
    assert report.results[0].protocol == "Anthropic Messages"
    assert report.results[0].ok is False
    assert report.results[1].protocol == "OpenAI Chat Completions"
    assert report.results[1].response_text == "hello"
    assert len(report.results) == 2
    assert "Calling Anthropic Messages: openai/test" in capsys.readouterr().out


def test_wallet_balance_parser_handles_nested_bff_response():
    snapshot = wallet_balance_from_response(
        {
            "body": {
                "wallet": {
                    "subId": "shared-id",
                    "subBalance": "99.99990000",
                    "subTotalAmount": "120.00000000",
                    "coinType": "ETH",
                }
            }
        },
        datetime(2026, 7, 25, tzinfo=timezone.utc),
    )

    assert snapshot.balance == "99.99990000"
    assert snapshot.money_id == "shared-id"
    assert snapshot.total_amount == "120.00000000"
    assert snapshot.coin_type == "ETH"
