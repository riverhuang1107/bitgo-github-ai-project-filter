import pytest
import httpx

from github_ai_daily.reasoning import (
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


def test_token_usage_supports_anthropic_and_reports_missing():
    usage = TokenUsage.from_response(
        {"usage": {"input_tokens": 12, "output_tokens": 3}}
    )
    assert usage.total_tokens == 15
    assert "input=12" in usage.format()
    assert "服务端未提供" in TokenUsage().format()


def test_http_error_includes_safe_server_detail():
    request = httpx.Request("POST", "https://example.test/v1/messages")
    response = httpx.Response(400, request=request)
    with pytest.raises(RuntimeError, match="invalid model"):
        _raise_for_status(response, {"error": {"message": "invalid model"}})
