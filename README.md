# GitHub AI Daily

跨平台 Python CLI：抓取 GitHub Trending 当日项目，用指定的 ECDSA 签名推理 API筛选 AI 项目，生成 Markdown/HTML 日报，并通过 Resend SMTP 发送 MIME 邮件。

## 运行要求

- Python 3.11+
- Windows，或支持 Secret Service/外部 Secret 命令的 Linux
- 可访问 GitHub、推理 API和 Resend
- 一个已创建并验证发件域名的 Resend 账号

Resend 的账号注册、域名所有权验证和服务商风控无法由本地程序绕过。完成这些基础设施准备后，工具的 `init` 为零交互：它使用部署 Secret 中的管理 Key 自动创建仅发送权限的 SMTP Key。

## 安装

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
```

## 无人值守初始化

注入以下 Secret/配置后运行：

```bash
export RESEND_MANAGEMENT_API_KEY="re_..."
export REASONING_API_MODEL="claude-4.6-opus"
export GITHUB_AI_MAIL_FROM="AI Daily <daily@verified.example>"
export GITHUB_AI_MAIL_TEST_TO="ops@example.com"
github-ai-daily init
```

PowerShell：

```powershell
$env:RESEND_MANAGEMENT_API_KEY = "re_..."
$env:REASONING_API_MODEL = "claude-4.6-opus"
$env:GITHUB_AI_MAIL_FROM = "AI Daily <daily@verified.example>"
$env:GITHUB_AI_MAIL_TEST_TO = "ops@example.com"
github-ai-daily init
```

初始化会：

1. 在当前目录初始化 Git（如果尚未初始化）。
2. 在用户配置目录生成权限受限的 ECDSA P-256 私钥。
3. 调用 Resend API创建 `sending_access` 子 Key。
4. 将子 Key写入安全 Secret 后端，并通过 `smtp.resend.com:587` 发测试邮件。
5. 将非敏感配置写入用户配置目录。

管理 Key从环境中读取后立即移除，且不会保存。密钥轮换时需要由部署系统再次注入管理 Key。

## Linux Secret 后端

桌面 Linux 默认使用 Secret Service。无桌面 Linux 必须配置三个命令：

```bash
export GITHUB_AI_SECRET_GET_CMD="/opt/secrets/get"
export GITHUB_AI_SECRET_PUT_CMD="/opt/secrets/put"
export GITHUB_AI_SECRET_DELETE_CMD="/opt/secrets/delete"
```

工具把 Secret 名称追加为最后一个参数；`put` 从标准输入接收值，`get` 向标准输出返回值。适配脚本可连接 Kubernetes Secret、systemd credentials、Vault 或其他组织批准的 Secret 管理器。未配置安全后端时工具会失败，不会把 SMTP Key写进普通文件。

## 使用

```bash
github-ai-daily generate
github-ai-daily generate --limit 20 --format html --output-dir reports
github-ai-daily run --to reader@example.com
github-ai-daily send output/report.html --to reader@example.com

github-ai-daily mail status
github-ai-daily mail test --to ops@example.com
RESEND_MANAGEMENT_API_KEY=re_... github-ai-daily mail rotate
RESEND_MANAGEMENT_API_KEY=re_... github-ai-daily mail remove
github-ai-daily reasoning test --model claude-4.6-opus --key /secure/ecdsa-private.pem
```

默认同时输出 Markdown 与 HTML：

```text
output/github-ai-trending_YYYY-MM-DD_HHMMSS.md
output/github-ai-trending_YYYY-MM-DD_HHMMSS.html
```

可选的 `GITHUB_TOKEN` 能提高 GitHub REST API限额。

## 推理 API签名

请求签名文本严格为：

```text
METHOD
/path
?raw=query
nonce
```

无 query 时省略 query 行。工具对该文本执行 SHA-256，再以 ECDSA P-256 对摘要生成 ASN.1/DER 签名，并发送：

- `X-Nonce`
- `X-Signature`（hex）
- `X-Public-Key`（SubjectPublicKeyInfo DER hex）

请求体采用 Anthropic Messages 风格。接口失败、返回非法 JSON、遗漏候选或创造仓库时，正式报告不会生成。

每次外部推理 API请求完成后，CLI 都会立即输出 input、output 和 total token。
如果服务端响应没有 `usage` 字段，会明确显示“服务端未提供”，不会估算或编造。
默认模型为已完成真实连通性验证的 `claude-4.6-opus`，仍可通过
`REASONING_API_MODEL` 或 `reasoning test --model` 覆盖。

## 测试

```bash
pytest
python -m github_ai_daily --help
```

自动测试使用本地 mock，不调用真实 GitHub、推理 API、Resend 或 SMTP。
