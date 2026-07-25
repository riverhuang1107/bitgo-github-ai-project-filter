from pathlib import Path


def test_model_check_workflow_has_schedule_secrets_and_artifact():
    workflow = Path(".github/workflows/bitgo-model-check.yml").read_text(encoding="utf-8")

    assert 'cron: "17 1 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "REASONING_INTERFACE_PRIVATE_KEY_PEM" in workflow
    assert "REASONING_MONEY_ID" in workflow
    assert "GMAIL_TOKEN_JSON" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "model-check --output-dir reports --send-email" in workflow
