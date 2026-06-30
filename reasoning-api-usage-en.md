# External Reasoning API Usage Guide

This document explains how this project integrates with, calls, and troubleshoots the external reasoning API. The current project uses “screening GitHub Trending candidate repositories, identifying which ones are AI projects, and generating Chinese categories, summaries, and selection reasons” as a sample scenario. This scenario is only a demonstration of structured reasoning API usage; it does not mean the API can only be used for GitHub project screening. The same integration pattern can be applied to other business workflows that need model reasoning, classification, summarization, or structured output.

## 1. API Positioning

The external reasoning API provides general-purpose reasoning capabilities. This project demonstrates it through an end-to-end sample workflow:

1. Collect candidate repository data from GitHub Trending.
2. Organize candidate data into an Anthropic Messages-style request body.
3. Use the new `X-Params` multi-chain wallet signature authentication by default; keep the old key-pair signing method as legacy.
4. Call the external reasoning API and receive structured JSON results.
5. Validate the result and generate Markdown and HTML reports.

In this sample, the model determines whether each candidate repository is an AI project and generates Chinese fields for the result. For other business use cases, the input data, system prompt, and output schema can be replaced as needed.

## 2. Default Configuration

The default project configuration is defined in `src/github_ai_daily/config.py`:

| Setting | Default value | Description |
| --- | --- | --- |
| `endpoint` | `https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages` | External reasoning API endpoint |
| `model` | `claude-4.6-opus` | Default reasoning model |
| `wallet_chain` | `ltc` | New wallet signing chain: `ltc`, `btc`, or `eth` |
| `wallet_address` | Empty | Wallet address |
| `money` | `10` | Amount |
| `money_id` | Empty | Amount ID |
| `signer_command` | Empty | Optional Go signer command path; empty uses the project default signer |
| `private_key_path` | Empty | ECDSA private key path for legacy key-pair authentication only |

Example `[reasoning]` configuration:

```toml
[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
wallet_chain = "ltc"
wallet_address = "YOUR_WALLET_ADDRESS"
money = "10"
money_id = "YOUR_MONEY_ID"
signer_command = ""

# legacy key-pair only
private_key_path = "/secure/ecdsa-private.pem"
```

The new wallet signature authentication can be overridden with environment variables:

```bash
export REASONING_API_MODEL="claude-4.6-opus"
export REASONING_PRIVATE_KEY="YOUR_WALLET_PRIVATE_KEY"
export REASONING_WALLET_CHAIN="ltc"
export REASONING_WALLET_ADDRESS="YOUR_WALLET_ADDRESS"
export REASONING_MONEY="10"
export REASONING_MONEY_ID="YOUR_MONEY_ID"
export REASONING_SIGNER_COMMAND=""
```

Do not write `REASONING_PRIVATE_KEY` to configuration files, README files, test fixtures, or commits. `ltc`/`btc` use WIF private keys, and `eth` uses a hex private key with or without a `0x` prefix.

## 3. Multi-Chain Wallet Generation and Connectivity Test

Cryptocurrency signing is implemented only by the Go signer in `tools/reasoning-signer`. The Python runtime calls the signer, builds `X-Params`, and sends the HTTP request; it does not directly implement wallet private-key signing.

### LTC Wallet

1. Generate a Litecoin mainnet wallet with a trusted Litecoin wallet or a tool specified by the deployment operator.
2. Export the Litecoin address and WIF private key.
3. Configure `wallet_chain = "ltc"` and inject the WIF private key through `REASONING_PRIVATE_KEY`.

LTC is the default chain and has been verified with real external reasoning API requests.

### BTC Wallet

1. Generate a Bitcoin mainnet wallet with a trusted Bitcoin wallet or a tool specified by the deployment operator.
2. Export the Bitcoin address and WIF private key. The address may be a server-registered `1...`, `3...`, or `bc1...` address.
3. Configure `wallet_chain = "btc"` and inject the WIF private key through `REASONING_PRIVATE_KEY`.

BTC is implemented with the same protocol; server acceptance depends on whether the wallet, address, amount, and amount ID have been registered and verified.

### ETH Wallet

1. Generate an Ethereum wallet with a trusted Ethereum wallet or a tool specified by the deployment operator.
2. Export the `0x...` address and hex private key. The private key may include or omit the `0x` prefix.
3. Configure `wallet_chain = "eth"` and inject the hex private key through `REASONING_PRIVATE_KEY`.

ETH is implemented with the new `X-Params` protocol and signs the 32-byte digest with a secp256k1 private key.

### Connectivity Test

```bash
REASONING_PRIVATE_KEY="YOUR_WALLET_PRIVATE_KEY" \
.venv/bin/github-ai-daily reasoning test \
  --chain ltc \
  --wallet-address YOUR_WALLET_ADDRESS \
  --money 10 \
  --money-id YOUR_MONEY_ID \
  --model claude-4.6-opus
```

You can also put the wallet parameters in configuration or environment variables, then run:

```bash
.venv/bin/github-ai-daily reasoning test
```

The connectivity test sends a lightweight request and expects the server to return an Anthropic-style `content` field. After the request completes, the CLI prints token usage returned by the server; if the server does not return `usage`, the CLI does not estimate it.

## 4. New `X-Params` Wallet Signature Authentication (Default)

The new authentication method builds a JSON object containing the wallet address, amount, amount ID, and signature, then base64-encodes it into the HTTP `X-Params` header.

Signing message:

```text
${wallet_address}${money}${money_id}
```

Signing process:

1. Encode `wallet_address + money + money_id` as UTF-8.
2. Compute `sha256.Sum256` over the message to get a 32-byte digest.
3. Sign the digest in Go according to the chain:
   - `ltc`: decode a Litecoin mainnet WIF private key and call `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`.
   - `btc`: decode a Bitcoin mainnet WIF private key and call `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`.
   - `eth`: decode an Ethereum hex private key and call `github.com/ethereum/go-ethereum/crypto.Sign`.
4. Base64-encode the signature bytes as `signature`.
5. Build the parameter JSON:

```json
{
  "wallet_address": "YOUR_WALLET_ADDRESS",
  "money": "10",
  "money_id": "YOUR_MONEY_ID",
  "signature": "BASE64_SIGNATURE"
}
```

6. UTF-8 encode and base64 the JSON string, then write it to `X-Params`.

Request headers:

| Header | Description |
| --- | --- |
| `Content-Type` | Always `application/json` |
| `X-Params` | Base64-encoded wallet signature parameter JSON |

Request example:

```bash
curl --location --request POST "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages" \
  --header "Content-Type: application/json" \
  --header "X-Params: BASE64_WALLET_PARAMS_JSON" \
  --data-raw '{
    "model": "claude-4.6-opus",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

At runtime, `ReasoningClient` sends `Content-Type` and `X-Params` by default. It no longer sends the legacy `X-Nonce/X-Signature/X-Public-Key` headers by default. To use a prebuilt signer, set `REASONING_SIGNER_COMMAND` or `signer_command`.

## 5. Legacy Key-Pair Signature Authentication (Retained)

The old method signs each request with an ECDSA P-256 private key. It is retained for compatibility with old deployments and historical request debugging, but it is not the default authentication path.

Generate an ECDSA P-256 private key:

```bash
.venv/bin/github-ai-daily keygen --path /secure/ecdsa-private.pem
```

Legacy connectivity test:

```bash
.venv/bin/github-ai-daily reasoning test \
  --model claude-4.6-opus \
  --key /secure/ecdsa-private.pem
```

Legacy signing message format:

```text
METHOD
/path
?raw=query
nonce
```

Notes:

- `METHOD` is uppercase, such as `POST`.
- The second line is the URL path; use `/` when there is no path.
- The query line is included only when the URL has a query string, and the raw query is preserved.
- The final line is a random nonce.

Legacy signing process:

1. Encode the signing message as UTF-8.
2. Compute SHA-256 over the message.
3. Generate an ASN.1/DER signature over the digest using ECDSA P-256.
4. Write the signature, nonce, and public key into request headers.

Legacy request headers:

| Header | Description |
| --- | --- |
| `Content-Type` | Always `application/json` |
| `X-Nonce` | Random nonce generated for each request |
| `X-Signature` | Hex-encoded DER signature |
| `X-Public-Key` | Hex-encoded SubjectPublicKeyInfo DER public key |

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

## 8. Token Usage

After every external reasoning API request completes, the CLI prints token usage:

```text
External reasoning API token usage: input=12, output=3, total=15
```

The project reads the `usage` field from the response and supports two naming conventions:

| Metric | Preferred field | Compatible field |
| --- | --- | --- |
| Input tokens | `input_tokens` | `prompt_tokens` |
| Output tokens | `output_tokens` | `completion_tokens` |
| Total tokens | `total_tokens` | Sum of input and output |

If the server does not provide a field, the CLI displays:

```text
Not provided by server
```

The project does not estimate or fabricate token data that the server does not return.

## 9. Common Failure Scenarios

The project stops formal report generation in the following cases:

| Scenario | Handling |
| --- | --- |
| HTTP status is not 2xx | Raises `Reasoning API returned HTTP ...` and includes server error details when available |
| `X-Params` authentication fails or returns 401 | Check that chain, wallet address, private key, amount, and amount ID match the server registration |
| Response is not valid JSON | Raises `Reasoning API did not return valid JSON` |
| JSON root is not an object | Raises `Reasoning API JSON root must be an object` |
| Missing `items` array | Raises `Reasoning response must contain an items array` |
| Unknown or duplicate repository returned | Raises an unknown or duplicate repository error |
| Input candidate omitted | Raises an omitted repositories error |
| No AI projects selected in the sample scenario | Raises `Reasoning API selected no AI projects` |

## 10. Security Notes

- Do not commit real wallet private keys, legacy ECDSA private keys, management tokens, or other secrets to the repository.
- Documentation, examples, and configuration templates should only contain placeholders.
- `ltc`/`btc` WIF private keys and `eth` hex private keys should only be injected through environment variables, CLI arguments, or an external secret manager.
- Wallet address, chain, amount, and amount ID must match the server registration; otherwise the API may return 401.
- Store legacy ECDSA private key files in a user configuration directory or secure directory, and restrict file permissions.
- Automated tests use local mocks and do not call real GitHub, the external reasoning API, Resend, or SMTP.

