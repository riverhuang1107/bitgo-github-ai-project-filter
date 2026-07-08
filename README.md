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
wallet_chain = "YOUR_WALLET_CHAIN"
wallet_address = "YOUR_WALLET_ADDRESS"
money = "YOUR_WALLET_MONEY"
# Optional existing record override; omit to auto-generate money_<timestamp>_<random>.
money_id = ""
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
2. 生成接口级 ECDSA P-256 私钥，用于 `X-Signature` 和 `X-Public-Key` 请求头。
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

只运行 `generate` 不需要配置这三个 SMTP Secret 命令，但仍需要通过 `REASONING_PRIVATE_KEY` 或部署 Secret 注入推理 API 钱包私钥。

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
REASONING_PRIVATE_KEY=... .venv/bin/github-ai-daily reasoning test --chain YOUR_WALLET_CHAIN --wallet-address YOUR_WALLET_ADDRESS --money YOUR_WALLET_MONEY
REASONING_NEW_WALLET=true .venv/bin/github-ai-daily reasoning test --chain eth --money YOUR_WALLET_MONEY

REASONING_ETH_PRIVATE_KEY=... .venv/bin/github-ai-daily bff wallet --chain eth --wallet-address YOUR_ETH_WALLET_ADDRESS
```

`generate` 只生成报告文件，不发送邮件。通过 agent 执行邮件命令时使用 Agent Mail；在非 agent 环境中，`run --to ...`、`send ... --to ...`、`mail test` 会通过 Resend SMTP 发送邮件。

## Bitgo BFF 钱包查询

`bff wallet` 会按 `SIGNING_GUIDE.md` 的 Tier1 规则对 `wallet_address` 做钱包私钥签名，生成只包含 `wallet_address` 和 `signature` 的 `X-Params`，然后请求：

- `GET /api/bff/v1/wallet`
- `GET /api/bff/v1/wallet/transactions`

示例：

```bash
export REASONING_ETH_PRIVATE_KEY="eth-hex-private-key"
.venv/bin/github-ai-daily bff wallet \
  --chain eth \
  --wallet-address 0x49e4f15e31fade852bbd0eb9f5d07bbc68b01a16 \
  --page 1 \
  --page-size 20
```

PowerShell：

```powershell
$env:REASONING_ETH_PRIVATE_KEY = "eth-hex-private-key"
python -m github_ai_daily bff wallet `
  --chain eth `
  --wallet-address 0x49e4f15e31fade852bbd0eb9f5d07bbc68b01a16 `
  --page 1 `
  --page-size 20
```

私钥也可用 `BFF_PRIVATE_KEY` 或 `REASONING_PRIVATE_KEY` 注入；不建议把真实私钥写入配置文件、README 或 shell 历史。

## 推理 API 签名

### 新版 X-Params 钱包签名（默认）

默认认证方法使用 `X-Params` 钱包业务签名，并叠加 `X-Nonce`、`X-Signature`、`X-Public-Key` 接口级 ECDSA 签名。Python CLI 负责组装请求和调用推理 API；所有加密货币私钥签名都由 Go signer 完成。

调用外部推理 API 前，agent 或人工操作方必须先确认本次使用的加密货币钱包类型和业务参数，不能默认复用某个已存在的钱包、示例 `X-Params` 或上一次请求的链类型。确认项至少包括 `wallet_chain`（`ltc`、`btc` 或 `eth`）、`wallet_address`、`money`，以及是使用已签名的 `X-Params` 还是用对应私钥重新生成钱包业务签名；缺少确认时应先询问用户，不应发起请求。`money_id` 由工具自动生成，必须唯一、不可预测，并适合服务端识别本次授权资金。

如果用户已经明确指定某一种加密货币钱包，工具可以查找配置中是否存在同币种钱包 profile；存在时可直接使用该币种的 `wallet_address`、`money`、已有 `money_id` 和 `signer_command`。不存在同币种 profile 时，工具不能把其他币种的旧配置混用到本次请求，必须由用户补充对应币种的钱包参数；如果没有已有 `money_id`，工具会自动生成新的授权资金 ID。

如果用户明确要求“使用一个新的钱包”发起请求，工具应使用 `--new-wallet` 或 `REASONING_NEW_WALLET=true` 为本次请求临时生成指定币种钱包，并用新钱包地址和新私钥生成 `X-Params`。新钱包私钥只用于本次进程内签名，不写入配置、README、日志或响应正文；`money` 必须由用户提供，或来自同币种 profile，不能从其他币种配置中继承；`money_id` 必须由工具为本次授权自动生成，格式类似 `money_<timestamp>_<random>`。

签名消息为：

```text
${wallet_address}${money}${money_id}
```

工具对该消息执行 `sha256.Sum256` 得到 32-byte digest，然后按 `wallet_chain` 选择签名方式：

- `ltc`：Litecoin mainnet WIF 私钥。普通地址使用 `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`；Taproot 地址（`ltc1p...`）使用 `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign`，签名结果为 64-byte Schnorr signature 后再 base64。
- `btc`：Bitcoin mainnet WIF 私钥。普通 BTC 地址（如 `1...`、`3...`、`bc1q...`）使用 `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`；Taproot 地址（`bc1p...`）先用 `github.com/btcsuite/btcd/txscript.TweakTaprootPrivKey(*privateKey, []byte{})` 调整 WIF 解码得到的内部私钥，再使用调整后的私钥调用 `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign`，签名结果为 64-byte Schnorr signature 后再 base64。
- `eth`：Ethereum hex 私钥（可带或不带 `0x`），使用 `github.com/ethereum/go-ethereum/crypto.Sign`。

签名结果 base64 编码后，组装 JSON：

```json
{
  "wallet_address": "...",
  "money": "YOUR_WALLET_MONEY",
  "money_id": "...",
  "signature": "..."
}
```

该 JSON 字符串再 base64 编码，放入请求 header `X-Params`。随后生成随机 `X-Nonce`，将 `X-Params + X-Nonce` 直接拼接后执行 SHA-256，再使用本地 ECDSA P-256 私钥生成 ASN.1/DER 签名 hex，放入 `X-Signature`，并把本地公钥 DER hex 放入 `X-Public-Key`。

```text
Content-Type: application/json
X-Params: <base64-json>
X-Nonce: <random-string>
X-Signature: <ecdsa-der-signature-hex>
X-Public-Key: <ecdsa-public-key-der-hex>
```

配置字段：

```toml
[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
wallet_chain = "YOUR_WALLET_CHAIN"
wallet_address = "YOUR_WALLET_ADDRESS"
money = "YOUR_WALLET_MONEY"
# Optional existing record override; omit to auto-generate money_<timestamp>_<random>.
money_id = ""
signer_command = ""

[reasoning.wallets.ltc]
wallet_address = "YOUR_LTC_WALLET_ADDRESS"
money = "YOUR_LTC_WALLET_MONEY"
# Optional existing record override.
money_id = ""
signer_command = ""

[reasoning.wallets.btc]
wallet_address = "YOUR_BTC_WALLET_ADDRESS"
money = "YOUR_BTC_WALLET_MONEY"
# Optional existing record override.
money_id = ""
signer_command = ""
```

环境变量可覆盖配置：

- `REASONING_PRIVATE_KEY`：通用钱包私钥；未提供币种专用私钥时需要。`ltc/btc` 为 WIF，`eth` 为 hex 私钥。
- `REASONING_LTC_PRIVATE_KEY`、`REASONING_BTC_PRIVATE_KEY`、`REASONING_ETH_PRIVATE_KEY`：可选；当显式指定对应币种时优先于通用 `REASONING_PRIVATE_KEY` 使用，便于多钱包环境按币种隔离私钥。
- `REASONING_NEW_WALLET`：可选；设置为 `true`、`1`、`yes` 或 `on` 时，为本次请求生成新的 `ltc/btc/eth` 钱包，不复用配置中的钱包地址或私钥。
- `REASONING_WALLET_CHAIN`：必需；`ltc`、`btc` 或 `eth`，必须由人提供，不能默认假设为固定链。
- `REASONING_WALLET_ADDRESS`
- `REASONING_MONEY`：必需；钱包面额金额，必须由人提供，不能默认假设为固定值。
- `REASONING_MONEY_ID`：可选；用于复用已有授权资金记录。创建钱包或创建 bitgo 钱包记录时不要要求用户手动提供，工具会自动生成类似 `money_20260707_a8f3c91b2e4d` 的唯一不可预测 ID。
- `REASONING_SIGNER_COMMAND`：可选；用于指定预编译 signer 或自定义 signer 命令。

`ltc` 已完成真实请求验证。`btc` 和 `eth` 已按同一协议在代码中实现，部署时需使用由人提供的对应链类型、钱包地址和私钥验证。地址类型会影响签名算法：非 Taproot 地址走 compact ECDSA，LTC `ltc1p...` Taproot 地址走 Schnorr，BTC `bc1p...` Taproot 地址走私钥 tweak 后的 Schnorr；如果服务端登记的钱包类型、地址派生方式、Taproot tweak 规则或签名算法不一致，可能返回 401。

### 请求响应示例

以下示例使用 ETH 钱包签名、`claude-4.6-opus` 模型，请求内容为“提供github上5个最热门的AI开源项目”。响应中的 `content`、`usage` 和计费字段为服务端真实返回值；余额、哈希和 token 数会随每次调用变化。

```json
{
  "content": [
    {
      "text": "# GitHub 上 5 个最热门的 AI 开源项目\n\n以下是截至 2025 年在 GitHub 上广受关注的 AI 开源项目：\n\n---\n\n## 1. 🤖 **TensorFlow**\n- **开发者：** Google\n- **⭐ Stars：** 187k+\n- **链接：** [github.com/tensorflow/tensorflow](https://github.com/tensorflow/tensorflow)\n- **简介：** 端到端的开源机器学习框架，广泛用于深度学习模型的训练与部署，支持多平台（移动端、Web、服务器）。\n\n---\n\n## 2. 🔥 **PyTorch**\n- **开发者：** Meta (Facebook)\n- **⭐ Stars：** 86k+\n- **链接：** [github.com/pytorch/pytorch](https://github.com/pytorch/pytorch)\n- **简介：** 灵活且高效的深度学习框架，以动态计算图著称，深受学术研究者和工业界喜爱。\n\n---\n\n## 3. 🦙 **llama.cpp**\n- **开发者：** Georgi Gerganov\n- **⭐ Stars：** 75k+\n- **链接：** [github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)\n- **简介：** 用纯 C/C++ 实现 LLaMA 模型推理，支持在消费级硬件（CPU）上本地运行大语言模型，推动了本地化 LLM 的普及。\n\n---\n\n## 4. 🧠 **LangChain**\n- **开发者：** LangChain AI\n- **⭐ Stars：** 100k+\n- **链接：** [github.com/langchain-ai/langchain](https://github.com/langchain-ai/langchain)\n- **简介：** 用于构建基于大语言模型（LLM）应用的开发框架，支持链式调用、RAG（检索增强生成）、Agent 等功能，是 LLM 应用开发的事实标准。\n\n---\n\n## 5. 🎨 **Stable Diffusion (Web UI)**\n- **开发者：** AUTOMATIC1111\n- **⭐ Stars：** 145k+\n- **链接：** [github.com/AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui)\n- **简介：** 基于 Stable Diffusion 的图形化界面，支持文本生成图像、图像修复、LoRA 等功能，是 AI 绘画领域最流行的开源工具。\n\n---\n\n> 📌 **补充提及：** 其他值得关注的项目还包括 **Hugging Face Transformers**（NLP 模型库）、**Open Interpreter**（本地代码解释器）、**Ollama**（本地运行 LLM 的工具）等。\n\n> ⚠️ Star 数为近似值，实际数据可能随时间变化，建议前往 GitHub 查看最新信息。",
      "type": "text"
    }
  ],
  "id": "msg_5f915d286439458aa18b6317052ea1ac",
  "model": "claude-4.6-opus",
  "role": "assistant",
  "stop_reason": "end_turn",
  "type": "message",
  "usage": {
    "balance": 487807775,
    "cache_creation": {
      "ephemeral_1h_input_tokens": 0,
      "ephemeral_5m_input_tokens": 0
    },
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "consume_amount": 2213980,
    "hash": "MzA0NTAyMjA1NTI3NTA0M2RhNTcyODg0NTE2NjkxODM0MzJjMjI1NzQ0ODFmMzhkNWU1YjVlYmMzNzU4Nzk2ZmFhYzVkYzZjMDIyMTAwZThjOGJkYjZiOTIxZTZjOTE4NmE4ODY4Y2M2MjE5NjVjZDIyNGEyNzkwODU0MTMyZGI5Y2JiY2VlYjc0ODZjYQ==",
    "input_token_unit_price": 500,
    "input_tokens": 23,
    "output_token_unit_price": 2520,
    "output_tokens": 874
  }
}
```

请求体采用 Anthropic Messages 风格。接口失败或返回非法 JSON 时，正式报告不会生成。若模型返回未知仓库名、重复仓库名或遗漏部分候选，CLI 会丢弃问题项，并用剩余有效 AI 候选继续补位生成报告。

`usage` 金额字段为服务端返回的整数缩放值，可按以下比例换算为实际金额：

- `input_token_unit_price` 和 `output_token_unit_price` 的实际价格为字段值乘以 `10^-5`，且单位价格表示每 1000 tokens 的价格。
- `consume_amount` 的实际消费金额为字段值乘以 `10^-8`。
- `balance` 的实际余额为字段值乘以 `10^-8`。

如果服务端响应没有 `usage` 字段，CLI 会输出 `"usage": null`，不会估算或编造。
默认模型为已完成真实连通性验证的 `claude-4.6-opus`，仍可通过
`REASONING_API_MODEL` 或 `reasoning test --model` 覆盖。

## 测试

```bash
.venv/bin/pytest
.venv/bin/python -m github_ai_daily --help
```

自动测试使用本地 mock，不调用真实 GitHub、推理 API、Resend 或 SMTP。
