import pytest
import httpx

from github_ai_daily.crypto import WalletAuth
from github_ai_daily.reasoning import (
    ReasoningClient,
    TokenUsage,
    _extract_json,
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


def test_http_error_includes_safe_server_detail():
    request = httpx.Request("POST", "https://example.test/v1/messages")
    response = httpx.Response(400, request=request)
    with pytest.raises(RuntimeError, match="invalid model"):
        _raise_for_status(response, {"error": {"message": "invalid model"}})


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
        lambda auth: {"Content-Type": "application/json", "X-Params": "encoded"},
    )
    auth = WalletAuth("ltc", "wallet", "10", "id", "private")
    client = ReasoningClient("https://example.test/v1/messages", "model-a", auth)
    client.client = FakeClient()

    client.test_access()

    assert captured["headers"]["X-Params"] == "encoded"
    assert "X-Public-Key" not in captured["headers"]
    assert "X-Signature" not in captured["headers"]
    assert "X-Nonce" not in captured["headers"]
    assert captured["body"]["model"] == "model-a"
