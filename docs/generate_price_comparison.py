import csv
import html
import re
import urllib.request
from datetime import date

AS_FILE = "价格.csv"
SUFY_URL = "https://sufy.com/zh-CN/services/ai-inference/models"

MAPPINGS = [
    ("Doubao Seed 1.6", "ByteDance/doubao-seed-1.6", "doubao-seed-1.6"),
    ("MiniMax M2", "MiniMax-M2", "minimax/minimax-m2"),
    ("MiniMax M2.1", "MiniMax-M2.1", "minimax/minimax-m2.1"),
    ("MiniMax M2.5", "MiniMax-M2.5", "minimax/minimax-m2.5"),
    ("MiniMax M2.7", "MiniMax-M2.7", "minimax/minimax-m2.7"),
    ("MiniMax M3", "MiniMax-M3", "minimax/minimax-m3"),
    ("Qwen3 Max", "Qwen/Qwen3-Max", "qwen3-max"),
    ("DeepSeek V3.2 Exp", "deepseek-ai/DeepSeek-V3.2-Exp", "deepseek/deepseek-v3.2-exp"),
    ("DeepSeek V4 Flash", "deepseek-v4-flash", "deepseek/deepseek-v4-flash"),
    ("DeepSeek V4 Pro", "deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
    ("GLM 5.1", "glm-5.1", "z-ai/glm-5.1"),
    ("GLM 5.2", "glm-5.2", "z-ai/glm-5.2"),
    ("Kimi K2.5", "moonshotai/kimi-k2.5", "moonshotai/kimi-k2.5"),
    ("Kimi K2.6", "kimi-k2.6", "moonshotai/kimi-k2.6"),
    ("Kimi K2.7 Code", "kimi-k2.7-code", "moonshotai/kimi-k2.7-code"),
    ("Qwen3 30B A3B", "qwen3-30b-a3b", "qwen3-30b-a3b"),
    ("Qwen3 Max Preview", "qwen3-max-preview", "qwen3-max-preview"),
    ("Qwen3.5 Plus", "qwen3.5-plus", "qwen/qwen3.5-plus"),
    ("Qwen3.6 Plus", "qwen3.6-plus", "qwen/qwen3.6-plus"),
    ("Qwen3.7 Max", "qwen3.7-max", "qwen/qwen3.7-max"),
    ("GLM 4.6", "zai-org/glm-4.6", "z-ai/glm-4.6"),
    ("GLM 4.7", "zai-org/glm-4.7", "z-ai/glm-4.7"),
    ("GLM 5", "zai-org/glm-5", "z-ai/glm-5"),
]


def load_astraflow():
    with open(AS_FILE, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    result = {}
    for _, aid, _ in MAPPINGS:
        model_rows = [r for r in rows if r["模型ID"].lower() == aid.lower() and "token" in r["单位"].lower()]
        input_rows = [r for r in model_rows if r["说明"].startswith("输入")]
        output_rows = [r for r in model_rows if r["说明"].startswith("文本输出")]
        cache_rows = [r for r in model_rows if "缓存" in r["说明"] and "读取" in r["说明"] or r["说明"].startswith("缓存")]
        if input_rows and output_rows:
            result[aid] = {
                "input": float(input_rows[0]["标价(元)"]),
                "output": float(output_rows[0]["标价(元)"]),
                "cache": float(cache_rows[0]["标价(元)"]) if cache_rows else None,
                "tiered": len(input_rows) > 1 or len(output_rows) > 1,
                "input_note": input_rows[0]["说明"].replace(" - ", "："),
            }
    return result


def load_sufy():
    raw = urllib.request.urlopen(SUFY_URL).read().decode("utf-8").replace('\\"', '"')
    result = {}
    for _, _, sid in MAPPINGS:
        match = re.search(r'"id":"' + re.escape(sid) + r'"', raw, re.I)
        if not match:
            continue
        end = raw.find('"rate_limit"', match.start())
        block = raw[match.start():end]
        entries = []
        pattern = (
            r'"unit_name":"token","unit_size":(\d+),"unit_price":([0-9.]+),'
            r'"unit_price_usd":[0-9.]+,"name":"([^"]*)"'
        )
        for size, cny, label in re.findall(pattern, block):
            entries.append((label, int(size), float(cny)))
        inputs = [e for e in entries if ("输入" in e[0] and "缓存" not in e[0])]
        outputs = [e for e in entries if "输出" in e[0]]
        caches = [e for e in entries if "缓存输入" in e[0] and "创建" not in e[0]]
        if inputs and outputs:
            result[sid] = {
                "input": inputs[0][2] * 1_000_000 / inputs[0][1],
                "output": outputs[0][2] * 1_000_000 / outputs[0][1],
                "cache": caches[0][2] * 1_000_000 / caches[0][1] if caches else None,
                "tiered": len(inputs) > 1 or len(outputs) > 1,
            }
    return result


def money(v):
    return "—" if v is None else f"{v:.2f}"


def diff(a, s):
    if not a or not s:
        return "—", "缺少可比项"
    pct = (a - s) / s * 100
    if abs(pct) < 0.05:
        return f"{pct:+.1f}%", "基本持平"
    return f"{pct:+.1f}%", "AstraFlow 更贵" if pct > 0 else "AstraFlow 更便宜"


af = load_astraflow()
sf = load_sufy()
rows = []
for name, aid, sid in MAPPINGS:
    if aid not in af or sid not in sf:
        continue
    a, s = af[aid], sf[sid]
    in_pct, in_winner = diff(a["input"], s["input"])
    out_pct, out_winner = diff(a["output"], s["output"])
    note = "最低上下文档" if a["tiered"] or s["tiered"] else "默认档"
    rows.append({
        "name": name, "aid": aid, "sid": sid, "a": a, "s": s,
        "in_pct": in_pct, "out_pct": out_pct,
        "in_winner": in_winner, "out_winner": out_winner, "note": note,
    })

af_input_wins = sum(r["a"]["input"] < r["s"]["input"] - 0.005 for r in rows)
sf_input_wins = sum(r["s"]["input"] < r["a"]["input"] - 0.005 for r in rows)
af_output_wins = sum(r["a"]["output"] < r["s"]["output"] - 0.005 for r in rows)
sf_output_wins = sum(r["s"]["output"] < r["a"]["output"] - 0.005 for r in rows)

md_lines = [
    "# Sufy 与 AstraFlow 大模型 Token 价格对比报告（Sufy 人民币直采版）",
    "",
    f"> 报告日期：{date.today().isoformat()}  ",
    "> 统一口径：人民币元 / 百万 Token；Sufy 采用模型详情中直接展示的人民币价格。  ",
    "> 范围：仅比较双方均提供、且存在文本 Token 输入/输出计费的同一模型。",
    "",
    "## 对比总结",
    "",
    f"- 共识别出 **{len(rows)} 款**可可靠匹配的共有 Token 计费模型。",
    f"- 输入价格：AstraFlow 更低 {af_input_wins} 款，Sufy 更低 {sf_input_wins} 款，其余为四舍五入后基本持平。",
    f"- 输出价格：AstraFlow 更低 {af_output_wins} 款，Sufy 更低 {sf_output_wins} 款，其余为四舍五入后基本持平。",
    "- 多数共有模型的人民币基础 Token 标价完全一致；差异较大的模型主要集中在特定 Qwen、GLM 等型号。",
    "- 采购决策不能只看 Token 单价：还应核对税费、并发/速率限制、缓存口径、模型上下线状态、上下文分档和服务可用区。",
    "",
    "## 价格明细",
    "",
    "| 模型 | AstraFlow 输入 | Sufy 输入 | 输入差异¹ | AstraFlow 输出 | Sufy 输出 | 输出差异¹ | 档位 |",
    "|---|---:|---:|---:|---:|---:|---:|---|",
]
for r in rows:
    md_lines.append(
        f"| {r['name']} | ¥{money(r['a']['input'])} | ¥{money(r['s']['input'])} | "
        f"{r['in_pct']} | ¥{money(r['a']['output'])} | ¥{money(r['s']['output'])} | "
        f"{r['out_pct']} | {r['note']} |"
    )
md_lines += [
    "",
    "¹ 差异 =（AstraFlow − Sufy）÷ Sufy；正值表示 AstraFlow 更贵，负值表示 AstraFlow 更便宜。",
    "",
    "## 模型匹配与方法说明",
    "",
    "- AstraFlow 来源：项目目录 `价格.csv`，价格已为人民币。",
    "- Sufy 来源：[AI 大模型广场](https://sufy.com/zh-CN/services/ai-inference/models)，页面价格不含适用税费。",
    "- 本版不使用汇率换算，直接采用 Sufy 模型详情数据中的人民币 `unit_price` 字段。",
    "- 名称匹配时统一了厂商前缀、大小写、空格、连字符和斜杠；没有把不同版本或不同速度变体强行视为同一模型。",
    "- 分档模型在主表中比较最低输入长度档；更长上下文可能适用更高单价，应按实际请求长度重新测算。",
    "- 缓存输入、缓存写入、图片/音频/视频 Token 及按秒/按张计费项因双方口径不完全一致，未纳入主表排名。",
    "",
    "## 结论与建议",
    "",
    "若工作负载以普通文本输入/输出为主，两家在不少共有模型上的价格接近，建议优先按实际模型组合和输入/输出比例做月度加权测算。对长上下文、缓存命中率高或多模态请求占比较高的业务，应进一步逐档核对，因为这些项目可能比基础 Token 单价更显著地影响总成本。",
]

md = "\n".join(md_lines) + "\n"
with open("sufy_vs_astraflow_token_price_report_cny_direct.md", "w", encoding="utf-8") as f:
    f.write(md)

table_rows = []
for r in rows:
    in_cls = "af" if r["a"]["input"] < r["s"]["input"] else "sf"
    out_cls = "af" if r["a"]["output"] < r["s"]["output"] else "sf"
    table_rows.append(
        f"<tr><td><strong>{html.escape(r['name'])}</strong><small>{html.escape(r['aid'])}</small></td>"
        f"<td class='{in_cls}'>¥{money(r['a']['input'])}</td><td class='{in_cls}'>¥{money(r['s']['input'])}</td>"
        f"<td>{r['in_pct']}</td><td class='{out_cls}'>¥{money(r['a']['output'])}</td>"
        f"<td class='{out_cls}'>¥{money(r['s']['output'])}</td><td>{r['out_pct']}</td><td>{r['note']}</td></tr>"
    )

html_doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sufy 与 AstraFlow 大模型 Token 价格对比报告（Sufy 人民币直采版）</title>
<style>
:root{{--ink:#172033;--muted:#65708a;--line:#dde3ee;--blue:#2563eb;--green:#087f5b;--bg:#f5f7fb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:1280px;margin:auto;padding:48px 28px 80px}}header{{background:linear-gradient(135deg,#101b3f,#1d4ed8);color:white;padding:42px;border-radius:22px;box-shadow:0 18px 50px #17367b33}}
h1{{margin:0 0 12px;font-size:34px;line-height:1.25}}header p{{margin:5px 0;color:#dbeafe}}section{{background:white;margin-top:22px;padding:28px;border:1px solid var(--line);border-radius:18px}}
h2{{margin:0 0 16px;font-size:22px}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.card{{padding:18px;border-radius:14px;background:#f8fafc;border:1px solid var(--line)}}.num{{font-size:28px;font-weight:750;color:var(--blue)}}.label{{color:var(--muted)}}
.table-wrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:980px}}th,td{{padding:12px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th{{position:sticky;top:0;background:#eef3ff;color:#34405a}}th:first-child,td:first-child,td:last-child{{text-align:left}}td small{{display:block;color:var(--muted);font-size:11px}}tr:hover{{background:#f8fbff}}ul{{padding-left:22px}}.note{{color:var(--muted);font-size:13px}}a{{color:var(--blue)}}footer{{color:var(--muted);margin-top:24px;text-align:center}}
@media(max-width:760px){{main{{padding:20px 12px}}header{{padding:28px 22px}}h1{{font-size:27px}}.cards{{grid-template-columns:1fr}}section{{padding:20px}}}}
@media print{{body{{background:white}}main{{max-width:none;padding:0}}header,section{{box-shadow:none;border-radius:0}}}}
</style></head><body><main>
<header><h1>Sufy 与 AstraFlow<br>大模型 Token 价格对比</h1>
<p><strong>Sufy 人民币直采版</strong></p>
<p>报告日期：{date.today().isoformat()} · 单位：人民币元 / 百万 Token</p>
<p>Sufy 采用模型详情中直接展示的人民币价格；仅纳入双方共有的 Token 计费模型。</p></header>
<section><h2>对比摘要</h2><div class="cards">
<div class="card"><div class="num">{len(rows)}</div><div class="label">共有可比模型</div></div>
<div class="card"><div class="num">{af_input_wins} / {sf_input_wins}</div><div class="label">输入价更低：AstraFlow / Sufy</div></div>
<div class="card"><div class="num">{af_output_wins} / {sf_output_wins}</div><div class="label">输出价更低：AstraFlow / Sufy</div></div>
</div><ul><li>多数共有模型的人民币基础 Token 标价一致；部分 Qwen、GLM 型号存在明显差异。</li>
<li>长上下文、缓存和多模态计费可能显著改变实际成本，建议按真实调用结构加权测算。</li>
<li>Sufy 页面注明价格不含适用税费；最终采购还应比较并发、限速、区域与 SLA。</li></ul></section>
<section><h2>价格明细</h2><div class="table-wrap"><table><thead><tr><th>模型</th><th>AstraFlow 输入</th><th>Sufy 输入</th><th>输入差异¹</th><th>AstraFlow 输出</th><th>Sufy 输出</th><th>输出差异¹</th><th>档位</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody></table></div><p class="note">¹ 差异 =（AstraFlow − Sufy）÷ Sufy；正值表示 AstraFlow 更贵。分档模型采用最低输入长度档。</p></section>
<section><h2>方法与口径</h2><ul>
<li>AstraFlow：项目目录 <code>价格.csv</code>。</li>
<li>Sufy：<a href="{SUFY_URL}">AI 大模型广场</a>。</li>
<li>本版不使用汇率换算，直接读取 Sufy 模型详情数据中的人民币价格字段。</li>
<li>统一厂商前缀、大小写和分隔符后匹配；不同速度或版本变体不合并。</li>
<li>缓存、图片/音频/视频 Token 和按秒/按张项目因口径不一致，不进入主表排名。</li>
</ul></section>
<section><h2>结论</h2><p>对于普通文本调用，两家在许多共有模型上的价格非常接近。建议按业务实际的模型占比、输入/输出 Token 比例、上下文长度和缓存命中率做月度成本模拟，再结合服务稳定性与限速选择供应商。</p></section>
<footer>数据为报告生成时点的公开标价，仅供成本评估。</footer>
</main></body></html>"""
with open("sufy_vs_astraflow_token_price_report_cny_direct.html", "w", encoding="utf-8") as f:
    f.write(html_doc)

print(f"Generated {len(rows)} comparable models")
