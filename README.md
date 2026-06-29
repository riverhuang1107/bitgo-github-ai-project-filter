# GitHub AI Daily

跨平台 Python CLI：抓取 GitHub Trending 当日项目，用指定的 ECDSA 签名推理 API筛选 AI 项目，生成 Markdown/HTML 日报；需要时也可以通过 Resend SMTP 发送 MIME 邮件。

## 运行要求

- Python 3.11+
- Windows、macOS 或 Linux
- 生成报告需要访问 GitHub 和推理 API
- 发送邮件才需要可访问 Resend，并准备一个已创建且验证发件域名的 Resend 账号

Resend 的账号注册、域名所有权验证和服务商风控无法由本地程序绕过。只运行 `generate` 不需要 Resend，也不会发送邮件。

## 安装

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

如果当前 shell 需要直接使用 `github-ai-daily` 命令，可以先激活虚拟环境：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\Activate.ps1
```

## 只生成报告的初始化

如果只执行 `github-ai-daily generate`，不发送邮件，可以做最小初始化：生成 ECDSA 私钥，并写入本机配置文件。这个流程不会调用 Resend，也不会写入 SMTP Secret。

macOS/Linux：

```bash
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/github-ai-daily"
KEY_PATH="$CONFIG_DIR/ecdsa-private.pem"

mkdir -p "$CONFIG_DIR"
test -f "$KEY_PATH" || .venv/bin/github-ai-daily keygen --path "$KEY_PATH"

cat > "$CONFIG_DIR/config.toml" <<EOF
[app]
output_dir = "output"

[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
private_key_path = "$KEY_PATH"

[mail]
from = ""
test_to = ""
host = "smtp.resend.com"
port = 587
username = "resend"
EOF
```

Linux 服务器上建议用运行任务的同一个系统用户执行以上命令，确保后续定时任务能读取同一份配置和私钥。

然后运行：

```bash
.venv/bin/github-ai-daily generate
```

默认同时输出 Markdown 与 HTML，且不会发送邮件：

```text
output/github-ai-trending_YYYY-MM-DD_HHMMSS.md
output/github-ai-trending_YYYY-MM-DD_HHMMSS.html
```

可选的 `GITHUB_TOKEN` 能提高 GitHub REST API限额：

```bash
export GITHUB_TOKEN="ghp_..."
```

## 邮件初始化

注入以下 Secret/配置后运行：

```bash
export RESEND_MANAGEMENT_API_KEY="re_..."
export REASONING_API_MODEL="claude-4.6-opus"
export GITHUB_AI_MAIL_TEST_TO="ops@example.com"
.venv/bin/github-ai-daily init
```

PowerShell：

```powershell
$env:RESEND_MANAGEMENT_API_KEY = "re_..."
$env:REASONING_API_MODEL = "claude-4.6-opus"
$env:GITHUB_AI_MAIL_TEST_TO = "ops@example.com"
.\.venv\Scripts\github-ai-daily init
```

默认发件人为 `Agent Mail <hhq4326@agent.qq.com>`。如果部署环境需要使用其他已经授权的发件身份，可以通过 `GITHUB_AI_MAIL_FROM` 覆盖，例如：

```bash
export GITHUB_AI_MAIL_FROM="Agent Mail <agent@verified.example>"
```

真实投递仍要求该邮箱或域名已被 Resend 允许发信；否则工具可以构造邮件，但 SMTP 服务端可能拒绝投递。

初始化会：

1. 在当前目录初始化 Git（如果尚未初始化）。
2. 在用户配置目录生成权限受限的 ECDSA P-256 私钥。
3. 调用 Resend API创建 `sending_access` 子 Key。
4. 将子 Key写入安全 Secret 后端，并通过 `smtp.resend.com:587` 发测试邮件。
5. 将非敏感配置写入用户配置目录。

管理 Key从环境中读取后立即移除，且不会保存。密钥轮换时需要由部署系统再次注入管理 Key。

如果需要创建 SMTP Key 但不发送初始化测试邮件，可以使用：

```bash
.venv/bin/github-ai-daily init --skip-mail-verification
```

这个选项仍会调用 Resend API创建 `sending_access` 子 Key，只是跳过 SMTP 测试邮件。

## Linux Secret 后端

Linux 上只有邮件相关流程需要 Secret 后端，因为 SMTP Key 不能写进普通文件。桌面 Linux 默认使用 Secret Service。无桌面 Linux 必须配置三个命令：

```bash
export GITHUB_AI_SECRET_GET_CMD="/opt/secrets/get"
export GITHUB_AI_SECRET_PUT_CMD="/opt/secrets/put"
export GITHUB_AI_SECRET_DELETE_CMD="/opt/secrets/delete"
```

工具把 Secret 名称追加为最后一个参数；`put` 从标准输入接收值，`get` 向标准输出返回值。适配脚本可连接 Kubernetes Secret、systemd credentials、Vault 或其他组织批准的 Secret 管理器。未配置安全后端时工具会失败，不会把 SMTP Key写进普通文件。

只运行 `keygen` 和 `generate` 不需要配置这三个命令。

## 使用

```bash
.venv/bin/github-ai-daily generate
.venv/bin/github-ai-daily generate --limit 20 --format html --output-dir reports
.venv/bin/github-ai-daily run --to reader@example.com
.venv/bin/github-ai-daily send output/report.html --to reader@example.com

.venv/bin/github-ai-daily mail status
.venv/bin/github-ai-daily mail test --to ops@example.com
RESEND_MANAGEMENT_API_KEY=re_... .venv/bin/github-ai-daily mail rotate
RESEND_MANAGEMENT_API_KEY=re_... .venv/bin/github-ai-daily mail remove
.venv/bin/github-ai-daily reasoning test --model claude-4.6-opus --key /secure/ecdsa-private.pem
```

`generate` 只生成报告文件，不发送邮件。`run --to ...`、`send ... --to ...`、`mail test` 会发送邮件。

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
.venv/bin/pytest
.venv/bin/python -m github_ai_daily --help
```

自动测试使用本地 mock，不调用真实 GitHub、推理 API、Resend 或 SMTP。
