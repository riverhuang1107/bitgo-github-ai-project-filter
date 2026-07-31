from datetime import datetime, timezone
from pathlib import Path

from github_ai_daily.models import ReportItem, Repository, Selection
from github_ai_daily.reports import (
    render_html,
    render_markdown,
    write_reasoning_request,
    write_reports,
)


def item() -> ReportItem:
    return ReportItem(
        Repository(
            full_name="owner/repo",
            url="https://github.com/owner/repo",
            stars=1200,
            stars_today=50,
            forks=100,
            language="Python",
            updated_at="2026-06-25T00:00:00Z",
            source="Hacker News Top Stories",
        ),
        Selection("owner/repo", True, "智能体", "项目简介", "增长快且属于 AI"),
    )


def test_report_rendering_and_files(tmp_path: Path):
    now = datetime(2026, 6, 25, 12, 30, tzinfo=timezone.utc)
    markdown = render_markdown([item()], now)
    html = render_html([item()], now)
    assert "1,200" in markdown
    assert "Hacker News Top Stories" in markdown
    assert "owner/repo" in html
    assert "Hacker News Top Stories" in html
    paths = write_reports([item()], tmp_path, "both", now)
    assert paths["markdown"].exists()
    assert paths["html"].exists()


def test_raw_reasoning_request_is_saved_as_json(tmp_path: Path):
    now = datetime(2026, 6, 25, 12, 30, tzinfo=timezone.utc)
    path = write_reasoning_request(
        {"model": "openai/gpt-5.4-nano", "messages": [{"role": "user"}]},
        tmp_path,
        now,
    )

    assert path.name == "github-ai-trending_request_2026-06-25_123000.json"
    assert path.read_text(encoding="utf-8") == (
        '{\n  "model": "openai/gpt-5.4-nano",\n'
        '  "messages": [\n    {\n      "role": "user"\n    }\n  ]\n}\n'
    )
