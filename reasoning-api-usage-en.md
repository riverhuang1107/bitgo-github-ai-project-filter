# External Reasoning API Usage Guide

This document explains how this project integrates with, calls, and troubleshoots the external reasoning API. The current project uses “screening GitHub Trending candidate repositories, identifying which ones are AI projects, and generating Chinese categories, summaries, and selection reasons” as a sample scenario. This scenario is only a demonstration of structured reasoning API usage; it does not mean the API can only be used for GitHub project screening. The same integration pattern can be applied to other business workflows that need model reasoning, classification, summarization, or structured output.

## 1. API Positioning

The external reasoning API provides general-purpose reasoning capabilities. This project demonstrates it through an end-to-end sample workflow:

1. Collect candidate repository data from GitHub Trending.
2. Organize candidate data into an Anthropic Messages-style request body.
3. Use the new `X-Params` multi-chain wallet signature authentication by default, together with interface-level `X-Nonce`, `X-Signature`, and `X-Public-Key` ECDSA headers.
4. Call the external reasoning API and receive structured JSON results.
5. Validate the result and generate Markdown and HTML reports.

In this sample, the model determines whether each candidate repository is an AI project and generates Chinese fields for the result. For other business use cases, the input data, system prompt, and output schema can be replaced as needed.

## 2. Default Configuration

The default project configuration is defined in `src/github_ai_daily/config.py`:

| Setting | Default value | Description |
| --- | --- | --- |
| `endpoint` | `https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages` | External reasoning API endpoint |
| `model` | `claude-4.6-opus` | Default reasoning model |
| `wallet_chain` | `YOUR_WALLET_CHAIN` | New wallet signing chain: `ltc`, `btc`, or `eth`; must be provided by a person |
| `wallet_address` | Empty | Wallet address |
| `money` | `YOUR_WALLET_MONEY` | Amount; must be provided by a person |
| `money_id` | Empty | Amount ID |
| `signer_command` | Empty | Optional Go signer command path; empty uses the project default signer |
| `private_key_path` | Empty | Interface-level ECDSA P-256 private key path used to generate `X-Signature` and `X-Public-Key` |

Example `[reasoning]` configuration:

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

The new wallet signature authentication can be overridden with environment variables:

```bash
export REASONING_API_MODEL="claude-4.6-opus"
export REASONING_PRIVATE_KEY="YOUR_WALLET_PRIVATE_KEY"
export REASONING_WALLET_CHAIN="YOUR_WALLET_CHAIN"
export REASONING_WALLET_ADDRESS="YOUR_WALLET_ADDRESS"
export REASONING_MONEY="YOUR_WALLET_MONEY"
export REASONING_MONEY_ID="YOUR_MONEY_ID"
export REASONING_SIGNER_COMMAND=""
```

Do not write `REASONING_PRIVATE_KEY` to configuration files, README files, test fixtures, or commits. `ltc`/`btc` use WIF private keys, and `eth` uses a hex private key with or without a `0x` prefix.

## 3. Multi-Chain Wallet Generation and Connectivity Test

Cryptocurrency signing is implemented only by the Go signer in `tools/reasoning-signer`. The Python runtime calls the signer to build `X-Params`, then uses the local ECDSA P-256 private key to sign `X-Params + X-Nonce` for the interface-level headers before sending the complete HTTP request; it does not directly implement wallet private-key signing.

### LTC Wallet

1. Generate a Litecoin mainnet wallet with a trusted Litecoin wallet or a tool specified by the deployment operator.
2. Export the Litecoin address and WIF private key.
3. Configure `wallet_chain = "ltc"` and inject the WIF private key through `REASONING_PRIVATE_KEY`.

LTC has been verified with real external reasoning API requests, but the chain must still be explicitly provided by a person.

### BTC Wallet

1. Generate a Bitcoin mainnet wallet with a trusted Bitcoin wallet or a tool specified by the deployment operator.
2. Export the Bitcoin address and WIF private key. The address may be a server-registered `1...`, `3...`, `bc1q...`, or `bc1p...` address.
3. Configure `wallet_chain = "btc"` and inject the WIF private key through `REASONING_PRIVATE_KEY`.

BTC is implemented with the same protocol; server acceptance depends on whether the wallet, address, amount, and amount ID have been registered and verified. Different BTC address types use different signing algorithms: regular addresses such as `1...`, `3...`, and `bc1q...` use compact ECDSA, while Taproot addresses (`bc1p...`) use Schnorr after private-key tweaking.

For Taproot addresses, the WIF-decoded key is the internal private key. The Go signer first calls `github.com/btcsuite/btcd/txscript.TweakTaprootPrivKey(*privateKey, []byte{})` to derive the tweaked Taproot private key; this example uses the key-path/no-script-root case, so the second argument is `[]byte{}`. It then calls `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign` with the tweaked private key to sign the 32-byte digest, producing a 64-byte Schnorr signature that is base64-encoded into the `signature` field.

### ETH Wallet

1. Generate an Ethereum wallet with a trusted Ethereum wallet or a tool specified by the deployment operator.
2. Export the `0x...` address and hex private key. The private key may include or omit the `0x` prefix.
3. Configure `wallet_chain = "eth"` and inject the hex private key through `REASONING_PRIVATE_KEY`.

ETH is implemented with the new `X-Params` protocol and signs the 32-byte digest with a secp256k1 private key.

### Connectivity Test

```bash
REASONING_PRIVATE_KEY="YOUR_WALLET_PRIVATE_KEY" \
.venv/bin/github-ai-daily reasoning test \
  --chain YOUR_WALLET_CHAIN \
  --wallet-address YOUR_WALLET_ADDRESS \
  --money YOUR_WALLET_MONEY \
  --money-id YOUR_MONEY_ID \
  --model claude-4.6-opus
```

You can also put the wallet parameters in configuration or environment variables, then run:

```bash
.venv/bin/github-ai-daily reasoning test
```

The connectivity test sends a lightweight request and expects the server to return an Anthropic-style `content` field. After the request completes, the CLI prints the complete `usage` JSON returned by the server; if the server does not return `usage`, the CLI prints `"usage": null` and does not estimate it.

## 4. New `X-Params` Wallet Signature Authentication (Default)

The new authentication method builds a JSON object containing the wallet address, amount, amount ID, and signature, then base64-encodes it into the HTTP `X-Params` header. Each request also carries interface-level ECDSA headers signed over `X-Params + X-Nonce`.

Signing message:

```text
${wallet_address}${money}${money_id}
```

Signing process:

1. Encode `wallet_address + money + money_id` as UTF-8.
2. Compute `sha256.Sum256` over the message to get a 32-byte digest.
3. Sign the digest in Go according to the chain:
   - `ltc`: decode a Litecoin mainnet WIF private key; regular addresses call `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`, and Taproot addresses (`ltc1p...`) call `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign`.
   - `btc`: decode a Bitcoin mainnet WIF private key; regular addresses such as `1...`, `3...`, and `bc1q...` call `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`; Taproot addresses (`bc1p...`) first call `github.com/btcsuite/btcd/txscript.TweakTaprootPrivKey(*privateKey, []byte{})`, then call `github.com/btcsuite/btcd/btcec/v2/schnorr.Sign` with the tweaked private key.
   - `eth`: decode an Ethereum hex private key and call `github.com/ethereum/go-ethereum/crypto.Sign`.
4. Base64-encode the signature bytes as `signature`.
5. Build the parameter JSON:

```json
{
  "wallet_address": "YOUR_WALLET_ADDRESS",
  "money": "YOUR_WALLET_MONEY",
  "money_id": "YOUR_MONEY_ID",
  "signature": "BASE64_SIGNATURE"
}
```

6. UTF-8 encode and base64 the JSON string, then write it to `X-Params`.
7. Generate a random `X-Nonce`, concatenate `X-Params + X-Nonce`, and compute SHA-256.
8. Sign the digest with the local ECDSA P-256 private key as ASN.1/DER hex in `X-Signature`, and send the DER public key hex in `X-Public-Key`.

Request headers:

| Header | Description |
| --- | --- |
| `Content-Type` | Always `application/json` |
| `X-Params` | Base64-encoded wallet signature parameter JSON |
| `X-Nonce` | Random string used in the interface-level ECDSA signature |
| `X-Signature` | ASN.1/DER hex signature over `X-Params + X-Nonce` |
| `X-Public-Key` | Local ECDSA DER public key hex |

Request example:

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

At runtime, `ReasoningClient` sends `Content-Type`, `X-Params`, `X-Nonce`, `X-Signature`, and `X-Public-Key` by default. To use a prebuilt wallet signer, set `REASONING_SIGNER_COMMAND` or `signer_command`.

## 5. Request and Response Example

The following example uses ETH wallet signing and the `claude-4.6-opus` model. The user prompt is "provide 5 of the most popular AI open-source projects on GitHub". The `content`, `usage`, and billing fields are real server-returned values; balance, hash, and token counts can change on each call.

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

The request body uses the Anthropic Messages style. If the API request fails or returns invalid JSON, the final report is not generated. If the model returns unknown repository names, duplicate repository names, or omits some candidates, the CLI discards invalid items and fills the report with the remaining valid AI candidates.

## 6. Request Body Format

The project uses an Anthropic Messages-style request body. In the sample screening scenario, the production request has this structure:

```json
{
  "model": "claude-4.6-opus",
  "max_tokens": 4096,
  "system": "You are a GitHub AI project screener. Only judge the input candidates; do not invent repositories...",
  "messages": [
    {
      "role": "user",
      "content": "Screen the following GitHub Trending candidates:\n[{\"full_name\":\"owner/repo\"}]"
    }
  ]
}
```

Candidate repository fields used by the sample scenario:

| Field | Description |
| --- | --- |
| `full_name` | Full repository name, such as `owner/repo` |
| `description` | Repository description |
| `language` | Primary language |
| `topics` | GitHub topics |
| `stars` | Total star count |
| `stars_today` | Stars added today |

These fields are specific to the GitHub Trending sample. For other business scenarios, replace the input fields and prompt according to the use case.

## 7. Response Format

The sample scenario requires the model to return a plain JSON object:

```json
{
  "items": [
    {
      "full_name": "owner/repo",
      "is_ai": true,
      "category": "Agent",
      "summary_zh": "Chinese summary",
      "reason_zh": "Selection reason"
    }
  ]
}
```

Validation rules:

- The JSON root must be an object.
- It must contain an `items` array.
- Every input candidate must be returned exactly once.
- Repositories outside the input are not allowed.
- Duplicate repositories are not allowed.
- `is_ai` is treated as an AI project only when it is strictly `true`.

The API response can carry the text through the Anthropic-style `content` field:

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

The project also supports `content` as a string, or text returned directly through a `text` field.

## 8. Usage Output

After every external reasoning API request completes, the CLI immediately prints the complete `usage` JSON returned by the server. The complete request and response example already includes the `usage` field, so this section does not repeat a standalone JSON code block.

The monetary fields in `usage` are integer scaled values returned by the server. Convert them to actual amounts as follows:

- The actual `input_token_unit_price` and `output_token_unit_price` values are the field value multiplied by `10^-5`, and the unit price is the price per 1000 tokens.
- The actual `consume_amount` value is the field value multiplied by `10^-8`.
- The actual `balance` value is the field value multiplied by `10^-8`.

If the server response has no `usage` field, the CLI prints `"usage": null`; it does not estimate or fabricate usage.

## 9. Common Failure Scenarios

The project stops formal report generation in the following cases:

| Scenario | Handling |
| --- | --- |
| HTTP status is not 2xx | Raises `Reasoning API returned HTTP ...` and includes server error details when available |
| `X-Params` authentication fails or returns 401 | Check that chain, wallet address, private key, amount, and amount ID match the server registration; for BTC, also confirm that the signing algorithm matches the registered address type |
| Response is not valid JSON | Raises `Reasoning API did not return valid JSON` |
| JSON root is not an object | Raises `Reasoning API JSON root must be an object` |
| Missing `items` array | Raises `Reasoning response must contain an items array` |
| Unknown or duplicate repository returned | Drops the problematic item and continues report generation with the remaining valid candidates |
| Input candidate omitted | Continues report generation with the valid candidates returned by the model |
| No AI projects selected in the sample scenario | Raises `Reasoning API selected no AI projects` |

## 10. Security Notes

- Do not commit real wallet private keys, management tokens, or other secrets to the repository.
- Documentation, examples, and configuration templates should only contain placeholders.
- `ltc`/`btc` WIF private keys and `eth` hex private keys should only be injected through environment variables, CLI arguments, or an external secret manager.
- Wallet address, chain, amount, and amount ID must match the server registration; otherwise the API may return 401.
- Automated tests use local mocks and do not call real GitHub, the external reasoning API, Resend, or SMTP.
