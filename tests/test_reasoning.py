import pytest
import httpx
from cryptography.hazmat.primitives.asymmetric import ec

from github_ai_daily.crypto import WalletAuth
from github_ai_daily.models import Repository
from github_ai_daily.reasoning import (
    ReasoningClient,
    TokenUsage,
    _extract_json,
    _openai_chat_endpoint,
    _is_deepseek_v4,
    _selection_max_tokens,
    _raise_for_status,
    _validate_selections,
)


def test_extract_anthropic_content_and_validate():
    data = _extract_json(
        {
            "content": [
                {
                    "type": "text",
                    "text": '{"items":[{"full_name":"a/b","is_ai":true,'
                    '"category":"Agent","summary_zh":"简介","reason_zh":"原因"}]}',
                }
            ]
        }
    )
    result = _validate_selections(data, {"a/b"})
    assert result[0].is_ai is True


def test_rejects_unknown_repository():
    with pytest.raises(ValueError, match="unknown"):
        _validate_selections(
            {
                "items": [
                    {
                        "full_name": "x/y",
                        "is_ai": True,
                        "category": "",
                        "summary_zh": "",
                        "reason_zh": "",
                    }
                ]
            },
            {"a/b"},
        )


def test_tolerant_validation_drops_unknown_and_duplicate_repositories():
    result = _validate_selections(
        {
            "items": [
                {
                    "full_name": "a/b",
                    "is_ai": True,
                    "category": "Agent",
                    "summary_zh": "简介",
                    "reason_zh": "原因",
                },
                {
                    "full_name": "typo/repo",
                    "is_ai": True,
                    "category": "Agent",
                    "summary_zh": "",
                    "reason_zh": "",
                },
                {
                    "full_name": "a/b",
                    "is_ai": True,
                    "category": "Agent",
                    "summary_zh": "重复",
                    "reason_zh": "重复",
                },
            ]
        },
        {"a/b", "c/d"},
        strict=False,
    )

    assert [item.full_name for item in result] == ["a/b"]


def test_token_usage_supports_anthropic_and_reports_missing():
    usage = TokenUsage.from_response(
        {
            "usage": {
                "input_tokens": 12,
                "output_tokens": 3,
                "cache_read_input_tokens": 0,
                "consume_amount": 2520,
                "hash": "abc",
            }
        }
    )
    assert usage.total_tokens == 15
    assert usage.raw == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cache_read_input_tokens": 0,
        "consume_amount": 2520,
        "hash": "abc",
    }
    assert "input=12" in usage.format()
    assert '"consume_amount": 2520' in usage.format_json()
    assert '"hash": "abc"' in usage.format_json()
    assert "服务端未提供" in TokenUsage().format()


def test_token_usage_supports_modelink_openai_cache_fields():
    usage = TokenUsage.from_response(
        {
            "usage": {
                "prompt_tokens": 2048,
                "completion_tokens": 8,
                "prompt_tokens_details": {
                    "cache_creation_tokens": 2000,
                    "cached_tokens": 2000,
                },
            }
        }
    )

    assert usage.input_tokens == 2048
    assert usage.output_tokens == 8
    assert usage.cache_creation_input_tokens == 2000
    assert usage.cache_read_input_tokens == 2000


def test_http_error_includes_safe_server_detail():
    request = httpx.Request("POST", "https://example.test/v1/messages")
    response = httpx.Response(400, request=request)
    with pytest.raises(RuntimeError, match="invalid model"):
        _raise_for_status(response, {"error": {"message": "invalid model"}})


def test_deepseek_v4_selection_request_disables_thinking():
    client = ReasoningClient(
        "https://example.test/v1/messages",
        "deepseek/deepseek-v4-flash",
        WalletAuth("ltc", "wallet", "10", "id", "private"),
        ec.generate_private_key(ec.SECP256R1()),
    )

    assert client.selection_request([])["thinking"] == {"type": "disabled"}
    assert _is_deepseek_v4("deepseek-v4-pro") is True
    assert _is_deepseek_v4("openai/gpt-5.4-nano") is False


def test_selection_request_scales_output_tokens_for_large_candidate_set():
    client = ReasoningClient(
        "https://example.test/v1/messages",
        "openai/gpt-5.4-nano",
        WalletAuth("ltc", "wallet", "10", "id", "private"),
        ec.generate_private_key(ec.SECP256R1()),
    )
    repositories = [
        Repository(f"owner/repo-{index}", f"https://github.com/owner/repo-{index}")
        for index in range(50)
    ]

    assert client.selection_request(repositories)["max_tokens"] == 13312
    assert _selection_max_tokens(10) == 4096


def test_select_records_http_status_and_response_on_failure(monkeypatch):
    class FakeClient:
        def post(self, endpoint, headers, json):
            request = httpx.Request("POST", endpoint)
            return httpx.Response(
                502,
                request=request,
                json={"error": {"message": "Model resources are currently busy."}},
            )

    monkeypatch.setattr("github_ai_daily.reasoning.wallet_signed_headers", lambda auth, key: {})
    client = ReasoningClient(
        "https://example.test/v1/messages",
        "openai/gpt-5.4",
        WalletAuth("ltc", "wallet", "10", "id", "private"),
        ec.generate_private_key(ec.SECP256R1()),
    )
    client.client = FakeClient()

    with pytest.raises(RuntimeError, match="HTTP 502"):
        client.select([])

    assert client.last_call is not None
    assert client.last_call.protocol == "Anthropic Messages"
    assert client.last_call.model == "openai/gpt-5.4"
    assert client.last_call.status_code == 502
    assert client.last_call.duration_ms >= 0
    assert client.last_call.data == {
        "error": {"message": "Model resources are currently busy."}
    }


def test_reasoning_client_uses_x_params_headers(monkeypatch):
    captured = {}

    class FakeClient:
        def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["body"] = json
            request = httpx.Request("POST", endpoint)
            return httpx.Response(
                200,
                request=request,
                json={"content": [{"type": "text", "text": "{\"status\":\"ok\"}"}]},
            )

        def close(self):
            pass

    monkeypatch.setattr(
        "github_ai_daily.reasoning.wallet_signed_headers",
        lambda auth, key: {
            "Content-Type": "application/json",
            "X-Params": "encoded",
            "X-Nonce": "nonce",
            "X-Signature": "signature",
            "X-Public-Key": "public-key",
        },
    )
    auth = WalletAuth("ltc", "wallet", "10", "id", "private")
    key = ec.generate_private_key(ec.SECP256R1())
    client = ReasoningClient("https://example.test/v1/messages", "model-a", auth, key)
    client.client = FakeClient()

    client.test_access()

    assert captured["headers"]["X-Params"] == "encoded"
    assert captured["headers"]["X-Public-Key"] == "public-key"
    assert captured["headers"]["X-Signature"] == "signature"
    assert captured["headers"]["X-Nonce"] == "nonce"
    assert captured["body"]["model"] == "model-a"


def test_reasoning_client_uses_openai_chat_completions_protocol(monkeypatch):
    captured = {}

    class FakeClient:
        def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["body"] = json
            request = httpx.Request("POST", endpoint)
            return httpx.Response(200, request=request, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("github_ai_daily.reasoning.wallet_signed_headers", lambda auth, key: {})
    client = ReasoningClient(
        "https://example.test/v1/messages",
        "model-a",
        WalletAuth("ltc", "wallet", "10", "id", "private"),
        ec.generate_private_key(ec.SECP256R1()),
    )
    client.client = FakeClient()

    response = client.test_model_openai("openai/test", "hello", 128)

    assert response.data["choices"][0]["message"]["content"] == "ok"
    assert captured["endpoint"] == "https://example.test/v1/chat/completions"
    assert captured["body"]["max_completion_tokens"] == 128
    assert "max_tokens" not in captured["body"]
    assert _openai_chat_endpoint("https://example.test/v1/messages/") == "https://example.test/v1/chat/completions"


def test_reasoning_client_uses_modelink_openai_cache_extension(monkeypatch):
    captured = {}

    class FakeClient:
        def post(self, endpoint, headers, json):
            captured["endpoint"] = endpoint
            captured["body"] = json
            request = httpx.Request("POST", endpoint)
            return httpx.Response(200, request=request, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("github_ai_daily.reasoning.wallet_signed_headers", lambda auth, key: {})
    client = ReasoningClient(
        "https://example.test/v1/messages",
        "model-a",
        WalletAuth("ltc", "wallet", "10", "id", "private"),
        ec.generate_private_key(ec.SECP256R1()),
    )
    client.client = FakeClient()

    client.test_model_openai_with_cached_prefix("anthropic/claude", "hello", 128, "cached prefix")

    assert captured["endpoint"] == "https://example.test/v1/chat/completions"
    assert captured["body"] == {
        "model": "anthropic/claude",
        "max_tokens": 128,
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "cached prefix",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": "hello"},
        ],
    }
