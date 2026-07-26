from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx

from github_ai_daily import model_check
from github_ai_daily.model_check import (
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

    report = run_model_check(
        FakeClient(),
        now=datetime(2026, 7, 25, 9, 17, tzinfo=timezone.utc),
        models=_models(),
    )
    terminal = capsys.readouterr().out

    assert report.model_count == 4
    assert report.success_count == 2
    assert report.fully_supported_model_count == 1
    assert report.input_tokens == 20
    assert report.output_tokens == 8
    assert report.reported_cost == Decimal("2.46913578")
    assert report.results[0].response_text == "hello"
    assert report.results[1].response_text == "openai hello"
    assert report.results[2].error_category == "模型不可用"
    assert report.results[2].raw_error_json == {"error": {"message": "invalid model"}}
    assert report.results[4].error_category == "响应格式异常"
    assert report.results[4].raw_error_text == "upstream unavailable"
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
    assert report.results[0].request_url == "https://api.example.test/v1/messages"
    assert report.results[1].request_url == "https://api.example.test/v1/chat/completions"
    assert report.results[6].error_category == "网络/超时"
    assert "[1/8] Calling Anthropic Messages: ok" in terminal
    assert "[2/8] Calling OpenAI Chat Completions: ok" in terminal
    assert "[3/8] FAILED bad HTTP 400" in terminal
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
    assert "请求 URL：https://api.example.test/v1/messages" in markdown
    assert "https://api.example.test/v1/chat/completions" in html
    assert "invalid model" in html
    assert "2.46913578" in markdown
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


def test_select_models_rejects_unknown_values_before_requesting_models():
    try:
        select_models(_models(), ["missing-model"])
    except ValueError as exc:
        assert "missing-model" in str(exc)
    else:
        raise AssertionError("Expected an unknown model selector error")


def test_model_check_tests_both_protocols_for_every_model(capsys):
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
