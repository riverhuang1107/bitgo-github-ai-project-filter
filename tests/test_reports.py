from datetime import datetime, timezone
from pathlib import Path

from github_ai_daily.models import ReportItem, Repository, Selection
from github_ai_daily.reports import render_html, render_markdown, write_reports


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
        ),
        Selection("owner/repo", True, "智能体", "项目简介", "增长快且属于 AI"),
    )


def test_report_rendering_and_files(tmp_path: Path):
    now = datetime(2026, 6, 25, 12, 30, tzinfo=timezone.utc)
    markdown = render_markdown([item()], now)
    html = render_html([item()], now)
    assert "1,200" in markdown
    assert "owner/repo" in html
    paths = write_reports([item()], tmp_path, "both", now)
    assert paths["markdown"].exists()
    assert paths["html"].exists()

