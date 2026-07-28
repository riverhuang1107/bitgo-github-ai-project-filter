from __future__ import annotations

import html
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .model_check import ModelCheckReport, ModelCheckResult
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


def render_model_check_markdown(report: ModelCheckReport) -> str:
    lines = [
        "# Bitgo 大模型连通性报告",
        "",
        f"> 生成时间：{report.generated_at.astimezone().isoformat(timespec='seconds')}",
        f"> 测试提示词：{report.prompt}",
        f"> max_tokens：{report.max_tokens}",
        f"> 模型列表来源：{report.model_source}",
        "",
        "## 总结",
        "",
        f"- 模型总数：{report.model_count}",
        f"- 协议测试次数：{len(report.results)}",
        f"- {'输入缓存已命中的模型' if report.input_cache_check else '双协议均成功的模型'}：{report.fully_supported_model_count}",
        f"- 成功协议测试：{report.success_count}",
        f"- 失败协议测试：{len(report.failures)}",
        f"- 总 input token：{report.input_tokens}",
        f"- 总 output token：{report.output_tokens}",
        f"- 总费用（服务端 consume_amount，已报部分）：{_format_decimal(report.reported_cost)}",
        f"- 未提供费用的成功模型：{report.missing_cost_count}",
        f"- 未提供 usage 的模型：{report.missing_usage_count}",
        (
            f"- money_id：`{report.money_id}`（本次执行新建，本次全部模型调用均复用）。"
            if report.money_id_created_for_run
            else f"- money_id：`{report.money_id}`（复用已有 ID，本次全部模型调用均复用）。"
        )
        if report.money_id_reused_within_run
        else "- money_id：未复用。",
        "",
    ]
    lines[-1:-1] = _markdown_wallet_balance(report)
    lines.extend(_markdown_failure_summary(report))
    lines.extend(["## 调用明细", ""])
    for index, result in enumerate(report.results, 1):
        lines.extend(
            [
                f"### {index}. {result.model.model_id} · {result.protocol}",
                "",
                f"- 模型名称：{result.model.name}",
                f"- 发行商：{result.model.provider}",
                f"- 状态：{'成功' if result.ok else '失败'}",
                f"- 测试协议：{result.protocol}",
                *(
                    [f"- 缓存阶段：{result.cache_stage}"]
                    if result.cache_stage
                    else []
                ),
                *(
                    [
                        "- 输入缓存命中："
                        + ("是" if result.input_cache_hit else "否")
                        + f"（cache_read_input_tokens={result.usage.cache_read_input_tokens if result.usage else '未提供'}）"
                    ]
                    if result.input_cache_hit is not None
                    else []
                ),
                f"- 请求 URL：{result.request_url or '未捕获'}",
                f"- HTTP 状态：{result.status_code if result.status_code is not None else '未收到响应'}",
                f"- 开始时间：{result.started_at.isoformat(timespec='seconds')}",
                f"- 耗时：{result.duration_ms} ms",
                f"- 文档价格：输入 ${result.model.input_price_usd_per_million}/百万 token，输出 ${result.model.output_price_usd_per_million}/百万 token",
            ]
        )
        if result.ok:
            lines.extend([f"- 响应内容：{result.response_text or '（空文本响应）'}"])
        else:
            lines.extend(
                [
                    f"- 错误分类：{result.error_category}",
                    f"- 错误信息：{result.error_message}",
                ]
            )
        lines.extend(
            [
                "- Raw request body：",
                "",
                "```json",
                _format_json(result.raw_request),
                "```",
                "- Raw response JSON：",
                "",
                "```json",
                _format_json(result.raw_response_json),
                "```",
            ]
        )
        lines.extend(["- usage：", "", "```json", _format_json(result.usage.raw if result.usage else None), "```"])
        if not result.ok and result.raw_error_json is not None:
            lines.extend(["", "- 失败 raw JSON：", "", "```json", _format_json(result.raw_error_json), "```"])
        elif not result.ok and result.raw_error_text:
            lines.extend(["", "- 失败原始文本（服务端未返回 JSON）：", "", "```text", result.raw_error_text, "```"])
        lines.append("")
    return "\n".join(lines)


def render_model_check_html(report: ModelCheckReport) -> str:
    failure_summary = _html_failure_summary(report)
    wallet_balance = _html_wallet_balance(report)
    rows = "".join(_model_check_row(index, result) for index, result in enumerate(report.results, 1))
    generated_at = html.escape(report.generated_at.astimezone().isoformat(timespec="seconds"))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Bitgo 大模型连通性报告</title>
<style>
body{{margin:0;background:#f5f7fb;color:#172033;font:15px/1.55 Arial,"Microsoft YaHei",sans-serif}}
.wrap{{max-width:1180px;margin:auto;padding:28px 16px 48px}}h1{{margin:0 0 5px}}h2{{margin-top:30px;font-size:20px}}
.meta{{color:#667085}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:18px 0}}
.metric,.panel{{background:#fff;border:1px solid #dfe5ef;border-radius:8px;padding:14px}}.metric b{{display:block;font-size:23px}}
.table-wrap{{overflow:auto;background:#fff;border:1px solid #dfe5ef;border-radius:8px}}table{{border-collapse:collapse;width:100%;min-width:980px}}
th,td{{padding:10px 12px;border-bottom:1px solid #e8ecf2;text-align:left;vertical-align:top}}th{{background:#f0f4fa;font-size:13px}}
.ok{{color:#027a48;font-weight:bold}}.fail{{color:#b42318;font-weight:bold}}code,pre{{font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#101828;color:#f2f4f7;padding:12px;border-radius:6px}}
details{{margin-top:8px}}summary{{cursor:pointer;color:#175cd3}}ul{{margin:8px 0;padding-left:20px}}
</style></head><body><main class="wrap"><h1>Bitgo 大模型连通性报告</h1>
<p class="meta">生成时间：{generated_at}<br>测试提示词：{html.escape(report.prompt)}<br>max_tokens：{report.max_tokens}<br>模型列表来源：{html.escape(report.model_source)}</p>
<section class="metrics"><div class="metric"><span>模型总数</span><b>{report.model_count}</b></div><div class="metric"><span>协议测试次数</span><b>{len(report.results)}</b></div><div class="metric"><span>{'输入缓存已命中' if report.input_cache_check else '双协议均成功'}</span><b>{report.fully_supported_model_count}</b></div><div class="metric"><span>成功协议测试</span><b>{report.success_count}</b></div><div class="metric"><span>失败协议测试</span><b>{len(report.failures)}</b></div><div class="metric"><span>总 input token</span><b>{report.input_tokens}</b></div><div class="metric"><span>总 output token</span><b>{report.output_tokens}</b></div><div class="metric"><span>总费用（服务端已报）</span><b>{_format_decimal(report.reported_cost)}</b></div></section>
<section class="panel"><h2>零钱包与授权</h2><p>money_id：<code>{html.escape(report.money_id)}</code>（{"本次执行新建" if report.money_id_created_for_run else "复用已有 ID"}，本次全部模型调用均复用）。</p>{wallet_balance}</section>
<section class="panel"><h2>失败总结</h2>{failure_summary}<p>未提供费用的成功模型：{report.missing_cost_count}；未提供 usage 的模型：{report.missing_usage_count}。</p></section>
<h2>调用明细</h2><div class="table-wrap"><table><thead><tr><th>#</th><th>模型</th><th>协议</th><th>状态</th><th>HTTP</th><th>耗时</th><th>响应 / 错误</th><th>usage</th></tr></thead><tbody>{rows}</tbody></table></div>
</main></body></html>"""


def write_model_check_reports(report: ModelCheckReport, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"bitgo-model-check_{report.generated_at.strftime('%Y-%m-%d_%H%M%S')}"
    markdown_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"
    markdown_path.write_text(render_model_check_markdown(report), encoding="utf-8")
    html_path.write_text(render_model_check_html(report), encoding="utf-8")
    return {"markdown": markdown_path, "html": html_path}


def _markdown_failure_summary(report: ModelCheckReport) -> list[str]:
    if not report.failures:
        return ["## 失败总结", "", "所有模型调用成功。", ""]
    groups: dict[str, list[str]] = {}
    for result in report.failures:
        groups.setdefault(result.error_category, []).append(f"{result.model.model_id}（{result.protocol}）")
    lines = ["## 失败总结", ""]
    for category, models in groups.items():
        lines.append(f"- **{category}**：{', '.join(models)}")
    lines.append("")
    return lines


def _html_failure_summary(report: ModelCheckReport) -> str:
    if not report.failures:
        return "<p class=\"ok\">所有模型调用成功。</p>"
    groups: dict[str, list[str]] = {}
    for result in report.failures:
        groups.setdefault(result.error_category, []).append(f"{result.model.model_id}（{result.protocol}）")
    items = "".join(
        f"<li><strong>{html.escape(category)}</strong>：{html.escape(', '.join(models))}</li>"
        for category, models in groups.items()
    )
    return f"<ul>{items}</ul>"


def _markdown_wallet_balance(report: ModelCheckReport) -> list[str]:
    snapshot = report.wallet_balance
    if snapshot is None:
        return ["- 最新零钱包余额：未查询。"]
    if snapshot.error:
        return [f"- 最新零钱包余额：查询失败（{snapshot.error}）。"]
    details = [f"- 最新零钱包余额（USD）：{snapshot.balance}"]
    if snapshot.total_amount:
        details.append(f"- 零钱包总授权金额（USD）：{snapshot.total_amount}")
    if snapshot.coin_type:
        details.append(f"- 充值币种：{snapshot.coin_type}")
    if snapshot.updated_at:
        details.append(f"- 零钱包更新时间：{snapshot.updated_at}")
    details.append(f"- 零钱包查询时间：{snapshot.retrieved_at.isoformat(timespec='seconds')}")
    return details


def _html_wallet_balance(report: ModelCheckReport) -> str:
    snapshot = report.wallet_balance
    if snapshot is None:
        return "<p>最新零钱包余额：未查询。</p>"
    if snapshot.error:
        return f"<p class=\"fail\">最新零钱包余额查询失败：{html.escape(snapshot.error)}</p>"
    items = [f"<li>最新零钱包余额（USD）：<strong>{html.escape(snapshot.balance)}</strong></li>"]
    if snapshot.total_amount:
        items.append(f"<li>零钱包总授权金额（USD）：{html.escape(snapshot.total_amount)}</li>")
    if snapshot.coin_type:
        items.append(f"<li>充值币种：{html.escape(snapshot.coin_type)}</li>")
    if snapshot.updated_at:
        items.append(f"<li>零钱包更新时间：{html.escape(snapshot.updated_at)}</li>")
    items.append(f"<li>零钱包查询时间：{html.escape(snapshot.retrieved_at.isoformat(timespec='seconds'))}</li>")
    return f"<ul>{''.join(items)}</ul>"


def _model_check_row(index: int, result: ModelCheckResult) -> str:
    status = "<span class=\"ok\">成功</span>" if result.ok else "<span class=\"fail\">失败</span>"
    detail = html.escape(result.response_text if result.ok else result.error_message)
    if not result.ok and result.raw_error_json is not None:
        detail += f"<details><summary>失败 raw JSON</summary><pre>{html.escape(_format_json(result.raw_error_json))}</pre></details>"
    elif not result.ok and result.raw_error_text:
        detail += f"<details><summary>失败原始文本</summary><pre>{html.escape(result.raw_error_text)}</pre></details>"
    cache_detail = ""
    if result.input_cache_hit is not None:
        cache_detail = (
            f"<br><small>Input cache: {'HIT' if result.input_cache_hit else 'MISS'} "
            f"(cache_read_input_tokens={result.usage.cache_read_input_tokens if result.usage else 'n/a'})</small>"
        )
    elif result.cache_stage:
        cache_detail = f"<br><small>Input-cache stage: {html.escape(result.cache_stage)}</small>"
    usage = _format_json(result.usage.raw if result.usage else None)
    raw_request = _format_json(result.raw_request)
    raw_response = _format_json(result.raw_response_json)
    return (
        f"<tr><td>{index}</td><td><code>{html.escape(result.model.model_id)}</code><br>{html.escape(result.model.name)}<br><small>{html.escape(result.model.provider)}</small></td>"
        f"<td>{html.escape(result.protocol)}{cache_detail}</td><td>{status}</td><td>{result.status_code if result.status_code is not None else '—'}</td><td>{result.duration_ms} ms</td>"
        f"<td>{detail}<details><summary>请求 URL</summary><pre>{html.escape(result.request_url or '未捕获')}</pre></details>"
        f"<details><summary>Raw request body</summary><pre>{html.escape(raw_request)}</pre></details>"
        f"<details><summary>Raw response JSON</summary><pre>{html.escape(raw_response)}</pre></details></td>"
        f"<td><details><summary>查看</summary><pre>{html.escape(usage)}</pre></details></td></tr>"
    )


def _format_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _format_decimal(value: Decimal) -> str:
    return f"{value:.8f}"
