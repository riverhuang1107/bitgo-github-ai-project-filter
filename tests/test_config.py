from pathlib import Path

from github_ai_daily.config import DEFAULT_MODEL, Settings


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


def test_default_model_is_verified_model():
    assert Settings().model == DEFAULT_MODEL == "claude-4.6-opus"
