from pathlib import Path

from github_ai_daily.config import DEFAULT_MAIL_FROM, DEFAULT_MODEL, Settings


def test_config_round_trip(tmp_path: Path):
    path = tmp_path / "config.toml"
    expected = Settings(
        model="model-a",
        private_key_path="/secure/key.pem",
        mail_from="daily@example.com",
        mail_test_to="reader@example.com",
    )
    expected.save(path)
    actual = Settings.load(path)
    assert actual.model == expected.model
    assert actual.mail_from == expected.mail_from


def test_default_mail_from_is_agent_mail():
    assert Settings().mail_from == DEFAULT_MAIL_FROM == "Agent Mail <hhq4326@agent.qq.com>"


def test_empty_mail_from_loads_default(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        "\n".join(
            [
                "[app]",
                'output_dir = "output"',
                "",
                "[reasoning]",
                'endpoint = "https://example.test/v1/messages"',
                'model = "claude-4.6-opus"',
                'private_key_path = "/secure/key.pem"',
                "",
                "[mail]",
                'from = ""',
                'test_to = "reader@example.com"',
                'host = "smtp.resend.com"',
                "port = 587",
                'username = "resend"',
            ]
        ),
        encoding="utf-8",
    )

    actual = Settings.load(path)

    assert actual.mail_from == DEFAULT_MAIL_FROM


def test_default_model_is_verified_model():
    assert Settings().model == DEFAULT_MODEL == "claude-4.6-opus"
