# GitHub AI Daily

跨平台 Python CLI：抓取 GitHub Trending 当日项目，用新版 `X-Params` 钱包签名认证的推理 API 筛选 AI 项目，生成 Markdown/HTML 日报。通过 agent 执行邮件命令时使用 Agent Mail；非 agent 环境才使用 Resend SMTP 发送 MIME 邮件。

## 运行要求

- Python 3.11+
- Go 1.20+（用于推理 API 钱包签名）
- Windows、macOS 或 Linux
- 生成报告需要访问 GitHub 和推理 API
- 通过 agent 执行邮件命令需要已授权 Agent Mail CLI
- 非 agent 环境发送邮件才需要可访问 Resend，并准备一个已创建且验证发件域名的 Resend 账号

Resend 的账号注册、域名所有权验证和服务商风控无法由本地程序绕过。只运行 `generate` 不需要 Agent Mail 或 Resend，也不会发送邮件。

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

如果只执行 `github-ai-daily generate`，不发送邮件，可以做最小初始化：写入推理 API 配置，并通过环境变量或部署平台 Secret 注入钱包私钥。这个流程不会调用 Resend，也不会写入 SMTP Secret。

macOS/Linux：

```bash
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/github-ai-daily"

mkdir -p "$CONFIG_DIR"

cat > "$CONFIG_DIR/config.toml" <<EOF
[app]
output_dir = "output"

[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
wallet_chain = "ltc"
wallet_address = "YOUR_WALLET_ADDRESS"
money = "10"
money_id = "YOUR_MONEY_ID"
signer_command = ""

[mail]
from = ""
test_to = ""
backend = "auto"
host = "smtp.resend.com"
port = 587
username = "resend"
EOF
```

Linux 服务器上建议用运行任务的同一个系统用户执行以上命令，确保后续定时任务能读取同一份配置。私钥不要写入配置文件，请使用环境变量或 Secret 管理器注入：

```bash
export REASONING_PRIVATE_KEY="ltc-or-btc-wif-or-eth-hex-private-key"
```

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

邮件发送分两种环境：

- 通过 agent 执行“发送邮件”“读取邮件”“整理邮件”等命令时，使用 Agent Mail CLI 和 Agent Mail skill。
- 在非 agent 环境运行本项目 CLI 的 `run --to ...`、`send ... --to ...`、`mail test` 时，才使用 Resend SMTP。

项目 CLI 默认使用 `mail.backend = "auto"`：检测到已安装且已授权的 `agently-cli` 时走 Agent Mail，否则回落 Resend SMTP。也可以通过 `GITHUB_AI_MAIL_BACKEND=agent|resend|auto` 临时覆盖。

### Agent 环境：Agent Mail

先在 agent 的运行环境中确认是否已经配置了 Agent Mail 发件身份。

- 如果已有 Agent Mail，可以直接通过 agent 执行邮件命令。
- 如果还没有 Agent Mail，请先按下面的步骤安装并授权 Agent Mail CLI。

参考 [Agent Mail CLI setup](https://agent.qq.com/doc/cli-setup.md)。

安装或更新 CLI：

```bash
npm install -g @tencent-qqmail/agently-cli
```

安装或更新 Agent Mail skill：

```bash
npx skills add https://agent.qq.com --skill -g -y
```

如果当前环境是 WorkBuddy，还需要安装 WorkBuddy skill：

```bash
if [ -d "$HOME/.workbuddy/skills" ]; then
  TMPDIR=$(mktemp -d)
  curl -L -o "$TMPDIR/skill.zip" "https://lightmake.site/api/v1/download?slug=agently-mail"
  mkdir -p "$HOME/.workbuddy/skills/agently-mail"
  unzip -o "$TMPDIR/skill.zip" -d "$HOME/.workbuddy/skills/agently-mail"
  rm -rf "$TMPDIR"
fi
```

执行 OAuth 授权：

```bash
agently-cli auth login
```

命令会输出授权 URL。点击或复制该链接到浏览器完成授权；授权完成后命令会自动退出。失败或超时时不要反复重试，先检查 CLI 输出的错误信息。

验证授权邮箱：

```bash
agently-cli +me
```

验证成功后，agent 邮件工作流使用该邮箱收发邮件。

### 非 Agent 环境：Resend SMTP

非 agent 环境发送本项目生成的报告时，注入以下 Secret/配置后运行：

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

Resend SMTP 的 From 必须使用已被 Resend 允许发信的邮箱或域名。如果需要显式指定 From，通过 `GITHUB_AI_MAIL_FROM` 注入完整发件身份，例如：

```bash
export GITHUB_AI_MAIL_FROM="Agent Mail <agent@verified.example>"
```

真实投递仍要求该邮箱或域名已被 Resend 允许发信；否则工具可以构造邮件，但 SMTP 服务端可能拒绝投递。

初始化会：

1. 在当前目录初始化 Git（如果尚未初始化）。
2. 保留生成 legacy ECDSA P-256 私钥的兼容流程；新版推理认证不使用它。
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

Linux 上只有非 agent 环境的 Resend SMTP 流程需要 Secret 后端，因为 SMTP Key 不能写进普通文件。桌面 Linux 默认使用 Secret Service。无桌面 Linux 必须配置三个命令：

```bash
export GITHUB_AI_SECRET_GET_CMD="/opt/secrets/get"
export GITHUB_AI_SECRET_PUT_CMD="/opt/secrets/put"
export GITHUB_AI_SECRET_DELETE_CMD="/opt/secrets/delete"
```

工具把 Secret 名称追加为最后一个参数；`put` 从标准输入接收值，`get` 向标准输出返回值。适配脚本可连接 Kubernetes Secret、systemd credentials、Vault 或其他组织批准的 Secret 管理器。未配置安全后端时工具会失败，不会把 SMTP Key写进普通文件。

只运行 `generate` 不需要配置这三个 SMTP Secret 命令，但仍需要通过 `REASONING_PRIVATE_KEY` 或部署 Secret 注入推理 API 钱包私钥。`keygen` 仅用于 legacy key pair 签名方法。

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
REASONING_PRIVATE_KEY=... .venv/bin/github-ai-daily reasoning test --chain ltc --wallet-address YOUR_WALLET_ADDRESS --money 10 --money-id YOUR_MONEY_ID
```

`generate` 只生成报告文件，不发送邮件。通过 agent 执行邮件命令时使用 Agent Mail；在非 agent 环境中，`run --to ...`、`send ... --to ...`、`mail test` 会通过 Resend SMTP 发送邮件。

## 推理 API 签名

### 新版 X-Params 钱包签名（默认）

默认认证方法使用 `X-Params` header。Python CLI 负责组装请求和调用推理 API；所有加密货币私钥签名都由 Go signer 完成。

签名消息为：

```text
${wallet_address}${money}${money_id}
```

工具对该消息执行 `sha256.Sum256` 得到 32-byte digest，然后按 `wallet_chain` 选择签名方式：

- `ltc`：Litecoin mainnet WIF 私钥，使用 `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`。
- `btc`：Bitcoin mainnet WIF 私钥。普通 BTC 地址（如 `1...`、`3...`、`bc1q...`）使用 `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`；Taproot 地址（`bc1p...`）先用 `github.com/btcsuite/btcd/txscript.TweakTaprootPrivKey(*privateKey, []byte{})` 调整 WIF 解码得到的内部私钥，再使用调整后的私钥调用 `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign`，签名结果为 64-byte Schnorr signature 后再 base64。
- `eth`：Ethereum hex 私钥（可带或不带 `0x`），使用 `github.com/ethereum/go-ethereum/crypto.Sign`。

签名结果 base64 编码后，组装 JSON：

```json
{
  "wallet_address": "...",
  "money": "10",
  "money_id": "...",
  "signature": "..."
}
```

该 JSON 字符串再 base64 编码，放入请求 header：

```text
Content-Type: application/json
X-Params: <base64-json>
```

配置字段：

```toml
[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
wallet_chain = "ltc"
wallet_address = "YOUR_WALLET_ADDRESS"
money = "10"
money_id = "YOUR_MONEY_ID"
signer_command = ""
```

环境变量可覆盖配置：

- `REASONING_PRIVATE_KEY`：必需；`ltc/btc` 为 WIF，`eth` 为 hex 私钥。
- `REASONING_WALLET_CHAIN`：`ltc`、`btc` 或 `eth`，默认 `ltc`。
- `REASONING_WALLET_ADDRESS`
- `REASONING_MONEY`
- `REASONING_MONEY_ID`
- `REASONING_SIGNER_COMMAND`：可选；用于指定预编译 signer 或自定义 signer 命令。

`ltc` 已完成真实请求验证。`btc` 和 `eth` 已按同一协议在代码中实现，部署时需使用对应链的钱包地址和私钥验证。BTC 地址类型会影响签名算法：非 Taproot 地址走 compact ECDSA，`bc1p...` Taproot 地址走私钥 tweak 后的 Schnorr；如果服务端登记的钱包类型、地址派生方式、Taproot tweak 规则或签名算法不一致，可能返回 401。

### 旧版 key pair 签名（legacy）

旧方法保留为兼容说明和 legacy helper，不再是默认推理认证路径。

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
