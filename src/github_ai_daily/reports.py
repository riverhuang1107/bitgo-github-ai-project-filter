from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .models import ReportItem


def build_items(repositories, selections, limit: int) -> list[ReportItem]:
    selected = {item.full_name: item for item in selections if item.is_ai}
    items = [
        ReportItem(repository=repo, selection=selected[repo.full_name])
        for repo in repositories
        if repo.full_name in selected
    ]
    return items[:limit]


def render_markdown(items: list[ReportItem], generated_at: datetime) -> str:
    lines = [
        "# GitHub 热门 AI 项目日报",
        "",
        f"> 生成时间：{generated_at.astimezone().isoformat(timespec='seconds')}",
        "",
    ]
    for rank, item in enumerate(items, 1):
        repo, choice = item.repository, item.selection
        lines.extend(
            [
                f"## {rank}. [{repo.full_name}]({repo.url})",
                "",
                f"- **简介：** {choice.summary_zh or repo.description}",
                f"- **AI 分类：** {choice.category}",
                f"- **入选原因：** {choice.reason_zh}",
                f"- **Stars：** {repo.stars:,}（今日 +{repo.stars_today:,}）",
                f"- **Forks：** {repo.forks:,}",
                f"- **主要语言：** {repo.language or '未知'}",
                f"- **最近更新：** {repo.updated_at or '未知'}",
                f"- **访问链接：** {repo.url}",
                "",
            ]
        )
    return "\n".join(lines)


def render_html(items: list[ReportItem], generated_at: datetime) -> str:
    cards = []
    for rank, item in enumerate(items, 1):
        repo, choice = item.repository, item.selection
        cards.append(
            f"""<section class="card">
<div class="rank">{rank}</div>
<h2><a href="{html.escape(repo.url)}">{html.escape(repo.full_name)}</a></h2>
<p class="summary">{html.escape(choice.summary_zh or repo.description)}</p>
<p><strong>AI 分类：</strong>{html.escape(choice.category)}</p>
<p><strong>入选原因：</strong>{html.escape(choice.reason_zh)}</p>
<div class="stats"><span>★ {repo.stars:,}</span><span>今日 +{repo.stars_today:,}</span>
<span>⑂ {repo.forks:,}</span><span>{html.escape(repo.language or "未知")}</span></div>
<p class="meta">最近更新：{html.escape(repo.updated_at or "未知")}</p>
</section>"""
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>GitHub 热门 AI 项目日报</title>
<style>
body{{margin:0;background:#f4f7fb;color:#172033;font:15px/1.65 Arial,"Microsoft YaHei",sans-serif}}
.wrap{{max-width:820px;margin:auto;padding:28px 16px}}h1{{margin-bottom:4px}}.date{{color:#667085}}
.card{{position:relative;background:#fff;border:1px solid #e5e9f0;border-radius:14px;padding:22px 22px 18px;margin:16px 0;box-shadow:0 4px 16px #1720330d}}
.rank{{position:absolute;right:18px;top:14px;color:#98a2b3;font-size:24px;font-weight:bold}}
h2{{margin:0 48px 8px 0;font-size:20px}}a{{color:#175cd3;text-decoration:none}}p{{margin:7px 0}}
.summary{{font-size:16px}}.stats{{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}}
.stats span{{background:#eef4ff;color:#3538cd;padding:3px 9px;border-radius:999px}}.meta{{color:#667085;font-size:13px}}
</style></head><body><main class="wrap"><h1>GitHub 热门 AI 项目日报</h1>
<p class="date">生成时间：{html.escape(generated_at.astimezone().isoformat(timespec="seconds"))}</p>
{''.join(cards)}</main></body></html>"""


def write_reports(
    items: list[ReportItem], output_dir: Path, output_format: str, generated_at: datetime
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"github-ai-trending_{generated_at.strftime('%Y-%m-%d_%H%M%S')}"
    paths: dict[str, Path] = {}
    if output_format in {"markdown", "both"}:
        paths["markdown"] = output_dir / f"{stem}.md"
        paths["markdown"].write_text(render_markdown(items, generated_at), encoding="utf-8")
    if output_format in {"html", "both"}:
        paths["html"] = output_dir / f"{stem}.html"
        paths["html"].write_text(render_html(items, generated_at), encoding="utf-8")
    return paths

