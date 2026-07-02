# 外部推理 API 使用文档

本文档说明本项目如何接入、调用和排查外部推理 API。项目当前以“筛选 GitHub Trending 候选仓库、判断哪些属于 AI 项目，并生成中文分类、简介和入选原因”作为示例展示，目的是演示外部推理 API 的结构化推理调用流程。该示例场景不代表 API 只能用于 GitHub 项目筛选；同样的接入方式也可用于其他需要模型推理、分类、摘要或结构化输出的业务。

## 1. API 定位

外部推理 API 提供通用推理能力。本项目把它用于一个完整示例流程：

1. 从 GitHub Trending 收集候选仓库数据。
2. 将候选数据组织为 Anthropic Messages 风格请求体。
3. 默认使用新版 `X-Params` 多链钱包签名认证，并叠加接口级 `X-Nonce`、`X-Signature`、`X-Public-Key` ECDSA 签名。
4. 调用外部推理 API 获取结构化 JSON 结果。
5. 校验结果后生成 Markdown 和 HTML 日报。

在该示例中，模型需要判断每个候选仓库是否属于 AI 项目，并为结果生成中文字段。实际业务可以替换输入数据、系统提示词和输出 schema。

## 2. 默认配置

项目默认配置位于 `src/github_ai_daily/config.py`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `endpoint` | `https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages` | 外部推理 API 请求地址 |
| `model` | `claude-4.6-opus` | 默认推理模型 |
| `wallet_chain` | `YOUR_WALLET_CHAIN` | 新版钱包签名链，可选 `ltc`、`btc`、`eth`，必须由人提供 |
| `wallet_address` | 空 | 钱包地址 |
| `money` | `YOUR_WALLET_MONEY` | 面额，必须由人提供 |
| `money_id` | 空 | 面额 ID |
| `signer_command` | 空 | 可选 Go signer 命令路径；为空时使用项目内默认 signer |
| `private_key_path` | 空 | 接口级 ECDSA P-256 私钥路径，用于生成 `X-Signature` 和 `X-Public-Key` |

用户配置文件中的 `[reasoning]` 配置示例：

```toml
[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
wallet_chain = "YOUR_WALLET_CHAIN"
wallet_address = "YOUR_WALLET_ADDRESS"
money = "YOUR_WALLET_MONEY"
money_id = "YOUR_MONEY_ID"
signer_command = ""

# interface-level ECDSA signing key
private_key_path = "/secure/ecdsa-private.pem"
```

新版钱包签名认证可通过环境变量覆盖：

```bash
export REASONING_API_MODEL="claude-4.6-opus"
export REASONING_PRIVATE_KEY="YOUR_WALLET_PRIVATE_KEY"
export REASONING_WALLET_CHAIN="YOUR_WALLET_CHAIN"
export REASONING_WALLET_ADDRESS="YOUR_WALLET_ADDRESS"
export REASONING_MONEY="YOUR_WALLET_MONEY"
export REASONING_MONEY_ID="YOUR_MONEY_ID"
export REASONING_SIGNER_COMMAND=""
```

`REASONING_PRIVATE_KEY` 不应写入配置文件、README、测试 fixture 或提交记录。`ltc`/`btc` 使用 WIF 私钥，`eth` 使用带或不带 `0x` 前缀的 hex 私钥。

## 3. 多链钱包生成与连通性测试

加密货币相关签名由 Go signer 统一实现，代码位于 `tools/reasoning-signer`。Python 运行时调用 signer 组装 `X-Params`，再使用本地 ECDSA P-256 私钥为 `X-Params + X-Nonce` 生成接口级签名，最后发送完整 HTTP 请求；Python 不直接实现钱包私钥签名。

### LTC 钱包

1. 使用可信的 Litecoin 钱包或部署方指定工具生成 Litecoin mainnet 钱包。
2. 导出 Litecoin 地址和 WIF 私钥。
3. 配置 `wallet_chain = "ltc"`，并通过 `REASONING_PRIVATE_KEY` 注入 WIF 私钥。

LTC 已通过真实外部推理 API 请求验证，但链类型仍必须由人明确提供。

### BTC 钱包

1. 使用可信的 Bitcoin 钱包或部署方指定工具生成 Bitcoin mainnet 钱包。
2. 导出 Bitcoin 地址和 WIF 私钥。地址可以是服务端已登记支持的 `1...`、`3...`、`bc1q...` 或 `bc1p...` 格式。
3. 配置 `wallet_chain = "btc"`，并通过 `REASONING_PRIVATE_KEY` 注入 WIF 私钥。

BTC 按同一协议完成代码支持；服务端是否接受取决于对应钱包、地址、面额和面额 ID 是否完成登记与验证。不同 BTC 地址类型使用不同签名算法：普通地址（如 `1...`、`3...`、`bc1q...`）使用 compact ECDSA；Taproot 地址（`bc1p...`）使用私钥 tweak 后的 Schnorr。

Taproot 地址签名时，WIF 解码得到的是内部私钥。Go signer 会先调用 `github.com/btcsuite/btcd/txscript.TweakTaprootPrivKey(*privateKey, []byte{})` 生成 Taproot 调整后的私钥；当前示例使用 key-path/no-script-root 场景，因此第二个参数为 `[]byte{}`。随后使用调整后的私钥调用 `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign` 对 32-byte digest 签名，得到 64-byte Schnorr signature，再 base64 成 `signature` 字段。

### ETH 钱包

1. 使用可信的 Ethereum 钱包或部署方指定工具生成 Ethereum 钱包。
2. 导出 `0x...` 地址和 hex 私钥。私钥可带或不带 `0x` 前缀。
3. 配置 `wallet_chain = "eth"`，并通过 `REASONING_PRIVATE_KEY` 注入 hex 私钥。

ETH 按新版 `X-Params` 协议完成代码支持，并使用 secp256k1 私钥对 32-byte digest 签名。

### 连通性测试

```bash
REASONING_PRIVATE_KEY="YOUR_WALLET_PRIVATE_KEY" \
.venv/bin/github-ai-daily reasoning test \
  --chain YOUR_WALLET_CHAIN \
  --wallet-address YOUR_WALLET_ADDRESS \
  --money YOUR_WALLET_MONEY \
  --money-id YOUR_MONEY_ID \
  --model claude-4.6-opus
```

也可以先把钱包参数写入配置或环境变量，然后直接运行：

```bash
.venv/bin/github-ai-daily reasoning test
```

连通性测试会发送一个轻量请求，要求服务端返回 Anthropic 风格的 `content` 字段。请求完成后，CLI 会输出服务端返回的完整 `usage` JSON；如果服务端未返回 `usage` 字段，CLI 会输出 `"usage": null`，不会自行估算。

## 4. 新版 `X-Params` 钱包签名认证（默认）

新版认证把钱包地址、面额、面额 ID 和签名组装为 JSON，然后 base64 编码到 HTTP header `X-Params` 中；请求还会携带基于 `X-Params + X-Nonce` 的接口级 ECDSA 签名 header。

签名消息为：

```text
${wallet_address}${money}${money_id}
```

签名流程：

1. 将 `wallet_address + money + money_id` 按 UTF-8 编码。
2. 对消息执行 `sha256.Sum256`，得到 32-byte digest。
3. 根据链类型使用 Go 完成签名：
   - `ltc`：按 Litecoin mainnet WIF 解码私钥；普通地址使用 `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`，Taproot 地址（`ltc1p...`）使用 `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign`。
   - `btc`：按 Bitcoin mainnet WIF 解码私钥；普通地址（如 `1...`、`3...`、`bc1q...`）使用 `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`；Taproot 地址（`bc1p...`）先使用 `github.com/btcsuite/btcd/txscript.TweakTaprootPrivKey(*privateKey, []byte{})` 调整私钥，再用调整后的私钥调用 `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign`。
   - `eth`：按 Ethereum hex 私钥解码，使用 `github.com/ethereum/go-ethereum/crypto.Sign`。
4. 将签名字节 base64 编码为 `signature`。
5. 组装参数 JSON：

```json
{
  "wallet_address": "YOUR_WALLET_ADDRESS",
  "money": "YOUR_WALLET_MONEY",
  "money_id": "YOUR_MONEY_ID",
  "signature": "BASE64_SIGNATURE"
}
```

6. 将上面的 JSON 字符串按 UTF-8 编码后 base64，写入 `X-Params`。
7. 生成随机 `X-Nonce`，将 `X-Params + X-Nonce` 直接拼接后执行 SHA-256。
8. 使用本地 ECDSA P-256 私钥生成 ASN.1/DER 签名 hex，写入 `X-Signature`，并把本地公钥 DER hex 写入 `X-Public-Key`。

请求头：

| Header | 说明 |
| --- | --- |
| `Content-Type` | 固定为 `application/json` |
| `X-Params` | base64 编码后的钱包签名参数 JSON |
| `X-Nonce` | 随机字符串，参与接口级 ECDSA 签名 |
| `X-Signature` | 对 `X-Params + X-Nonce` 签名后的 ASN.1/DER hex |
| `X-Public-Key` | 本地 ECDSA 公钥 DER hex |

请求示例：

```bash
curl --location --request POST "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages" \
  --header "Content-Type: application/json" \
  --header "X-Params: BASE64_WALLET_PARAMS_JSON" \
  --header "X-Nonce: RANDOM_NONCE" \
  --header "X-Signature: ECDSA_SIGNATURE_HEX" \
  --header "X-Public-Key: ECDSA_PUBLIC_KEY_HEX" \
  --data-raw '{
    "model": "claude-4.6-opus",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

在项目运行时，`ReasoningClient` 默认同时发送 `Content-Type`、`X-Params`、`X-Nonce`、`X-Signature` 和 `X-Public-Key`。如需使用预编译 signer，可设置 `REASONING_SIGNER_COMMAND` 或配置 `signer_command`。

## 5. 请求响应示例

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

## 6. 请求体格式

项目使用 Anthropic Messages 风格请求体。示例场景中的正式筛选请求结构如下：

```json
{
  "model": "claude-4.6-opus",
  "max_tokens": 4096,
  "system": "你是 GitHub AI 项目筛选器。只判断输入候选，不得创造仓库...",
  "messages": [
    {
      "role": "user",
      "content": "筛选以下 GitHub Trending 候选：\n[{\"full_name\":\"owner/repo\"}]"
    }
  ]
}
```

示例场景传入的候选仓库字段包括：

| 字段 | 说明 |
| --- | --- |
| `full_name` | 仓库完整名称，例如 `owner/repo` |
| `description` | 仓库描述 |
| `language` | 主要语言 |
| `topics` | GitHub topics |
| `stars` | 总 star 数 |
| `stars_today` | 当日新增 star 数 |

这些字段服务于 GitHub Trending 示例。接入其他业务时，可以按业务需要替换输入字段和提示词。

## 7. 响应格式

示例场景要求模型返回纯 JSON 对象：

```json
{
  "items": [
    {
      "full_name": "owner/repo",
      "is_ai": true,
      "category": "Agent",
      "summary_zh": "中文简介",
      "reason_zh": "入选原因"
    }
  ]
}
```

校验规则：

- JSON 根节点必须是对象。
- 必须包含 `items` 数组。
- 每个输入候选都必须返回一次。
- 不允许返回输入之外的仓库。
- 不允许重复返回同一个仓库。
- `is_ai` 只有严格为 `true` 时才视为 AI 项目。

API 响应可以通过 Anthropic 风格 `content` 字段承载文本：

```json
{
  "content": [
    {
      "type": "text",
      "text": "{\"items\":[]}"
    }
  ]
}
```

项目也兼容 `content` 为字符串，或通过 `text` 字段直接返回文本。

## 8. Usage 输出

每次外部推理 API 请求完成后，CLI 都会立即输出服务端返回的完整 `usage` JSON。完整请求响应示例中已包含 `usage` 字段，因此本节不再单独重复展示 JSON 代码块。

`usage` 金额字段为服务端返回的整数缩放值，可按以下比例换算为实际金额：

- `input_token_unit_price` 和 `output_token_unit_price` 的实际价格为字段值乘以 `10^-5`，且单位价格表示每 1000 tokens 的价格。
- `consume_amount` 的实际消费金额为字段值乘以 `10^-8`。
- `balance` 的实际余额为字段值乘以 `10^-8`。

如果服务端响应没有 `usage` 字段，CLI 会输出 `"usage": null`，不会估算或编造。

## 9. 常见失败场景

项目会在以下情况下停止生成正式报告：

| 场景 | 处理方式 |
| --- | --- |
| HTTP 非 2xx | 抛出 `Reasoning API returned HTTP ...`，并尽量附带服务端错误信息 |
| `X-Params` 认证失败或返回 401 | 检查链类型、钱包地址、私钥、面额、面额 ID 是否与服务端登记信息一致；BTC 还需确认地址类型对应的签名算法是否与服务端登记一致 |
| 响应不是合法 JSON | 抛出 `Reasoning API did not return valid JSON` |
| JSON 根节点不是对象 | 抛出 `Reasoning API JSON root must be an object` |
| 缺少 `items` 数组 | 抛出 `Reasoning response must contain an items array` |
| 返回未知或重复仓库 | 丢弃问题项，使用剩余有效候选继续生成报告 |
| 遗漏输入候选 | 使用已返回的有效候选继续补位生成报告 |
| 示例场景中没有筛选出 AI 项目 | 抛出 `Reasoning API selected no AI projects` |

## 10. 安全注意事项

- 不要将真实钱包私钥、管理 token 或其他密钥写入仓库。
- 文档、示例和配置模板中只应保留占位符。
- `ltc`/`btc` 的 WIF 私钥和 `eth` 的 hex 私钥只应通过环境变量、CLI 参数或外部 secret manager 注入。
- 钱包地址、链类型、面额和面额 ID 必须与服务端登记信息一致，否则可能返回 401。
- 自动测试使用本地 mock，不会调用真实 GitHub、外部推理 API、Resend 或 SMTP。
