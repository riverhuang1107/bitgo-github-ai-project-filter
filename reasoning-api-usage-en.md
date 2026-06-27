# External Reasoning API Usage Guide

This document explains how this project integrates with, calls, and troubleshoots the external reasoning API. The current project uses “screening GitHub Trending candidate repositories, identifying which ones are AI projects, and generating Chinese categories, summaries, and selection reasons” as a sample scenario. This scenario is only a demonstration of structured reasoning API usage; it does not mean the API can only be used for GitHub project screening. The same integration pattern can be applied to other business workflows that need model reasoning, classification, summarization, or structured output.

## 1. API Positioning

The external reasoning API provides general-purpose reasoning capabilities. This project demonstrates it through an end-to-end sample workflow:

1. Collect candidate repository data from GitHub Trending.
2. Organize candidate data into an Anthropic Messages-style request body.
3. Sign the request with an ECDSA P-256 private key.
4. Call the external reasoning API and receive structured JSON results.
5. Validate the result and generate Markdown and HTML reports.

In this sample, the model determines whether each candidate repository is an AI project and generates Chinese fields for the result. For other business use cases, the input data, system prompt, and output schema can be replaced as needed.

## 2. Default Configuration

The default project configuration is defined in `src/github_ai_daily/config.py`:

| Setting | Default value | Description |
| --- | --- | --- |
| `endpoint` | `https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages` | External reasoning API endpoint |
| `model` | `claude-4.6-opus` | Default reasoning model |
| `private_key_path` | Empty | ECDSA private key path, written after initialization |

Example `[reasoning]` configuration:

```toml
[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
private_key_path = "/secure/ecdsa-private.pem"
```

The model can also be overridden with an environment variable:

```bash
export REASONING_API_MODEL="claude-4.6-opus"
```

## 3. Private Key Generation and Connectivity Test

Generate an ECDSA P-256 private key:

```bash
.venv/bin/github-ai-daily keygen --path /secure/ecdsa-private.pem
```

Test whether the external reasoning API is reachable:

```bash
.venv/bin/github-ai-daily reasoning test \
  --model claude-4.6-opus \
  --key /secure/ecdsa-private.pem
```

The connectivity test sends a lightweight request and expects the server to return an Anthropic-style `content` field. After the request completes, the CLI prints token usage statistics.

## 4. Request Signing

Every request is signed with the ECDSA P-256 private key. The signing message format is:

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

Signing process:

1. Encode the signing message as UTF-8.
2. Compute SHA-256 over the message.
3. Generate an ASN.1/DER signature over the digest using ECDSA P-256.
4. Write the signature, nonce, and public key into request headers.

Request headers:

| Header | Description |
| --- | --- |
| `Content-Type` | Always `application/json` |
| `X-Nonce` | Random nonce generated for each request |
| `X-Signature` | Hex-encoded DER signature |
| `X-Public-Key` | Hex-encoded SubjectPublicKeyInfo DER public key |

## 5. Request Body Format

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

## 6. Response Format

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

## 7. Token Usage

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

## 8. Common Failure Scenarios

The project stops formal report generation in the following cases:

| Scenario | Handling |
| --- | --- |
| HTTP status is not 2xx | Raises `Reasoning API returned HTTP ...` and includes server error details when available |
| Response is not valid JSON | Raises `Reasoning API did not return valid JSON` |
| JSON root is not an object | Raises `Reasoning API JSON root must be an object` |
| Missing `items` array | Raises `Reasoning response must contain an items array` |
| Unknown or duplicate repository returned | Raises an unknown or duplicate repository error |
| Input candidate omitted | Raises an omitted repositories error |
| No AI projects selected in the sample scenario | Raises `Reasoning API selected no AI projects` |

## 9. Security Notes

- Do not commit real private keys, management tokens, or other secrets to the repository.
- Documentation, examples, and configuration templates should only contain placeholders.
- Store the private key in a user configuration directory or secure directory, and restrict file permissions.
- Automated tests use local mocks and do not call real GitHub, the external reasoning API, Resend, or SMTP.

