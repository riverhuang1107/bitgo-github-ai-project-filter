# 外部推理 API 使用文档

本文档说明本项目如何接入、调用和排查外部推理 API。项目当前以“筛选 GitHub Trending 候选仓库、判断哪些属于 AI 项目，并生成中文分类、简介和入选原因”作为示例展示，目的是演示外部推理 API 的结构化推理调用流程。该示例场景不代表 API 只能用于 GitHub 项目筛选；同样的接入方式也可用于其他需要模型推理、分类、摘要或结构化输出的业务。

## 1. API 定位

外部推理 API 提供通用推理能力。本项目把它用于一个完整示例流程：

1. 从 GitHub Trending 收集候选仓库数据。
2. 将候选数据组织为 Anthropic Messages 风格请求体。
3. 使用 ECDSA P-256 私钥对请求进行签名。
4. 调用外部推理 API 获取结构化 JSON 结果。
5. 校验结果后生成 Markdown 和 HTML 日报。

在该示例中，模型需要判断每个候选仓库是否属于 AI 项目，并为结果生成中文字段。实际业务可以替换输入数据、系统提示词和输出 schema。

## 2. 默认配置

项目默认配置位于 `src/github_ai_daily/config.py`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `endpoint` | `https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages` | 外部推理 API 请求地址 |
| `model` | `claude-4.6-opus` | 默认推理模型 |
| `private_key_path` | 空 | ECDSA 私钥路径，需要初始化后写入 |

用户配置文件中的 `[reasoning]` 配置示例：

```toml
[reasoning]
endpoint = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
model = "claude-4.6-opus"
private_key_path = "/secure/ecdsa-private.pem"
```

模型也可以通过环境变量覆盖：

```bash
export REASONING_API_MODEL="claude-4.6-opus"
```

## 3. 私钥生成与连通性测试

生成 ECDSA P-256 私钥：

```bash
.venv/bin/github-ai-daily keygen --path /secure/ecdsa-private.pem
```

测试外部推理 API 是否可访问：

```bash
.venv/bin/github-ai-daily reasoning test \
  --model claude-4.6-opus \
  --key /secure/ecdsa-private.pem
```

连通性测试会发送一个轻量请求，要求服务端返回 Anthropic 风格的 `content` 字段。请求完成后，CLI 会输出 token 使用统计。

## 4. 请求签名

每次请求都会使用 ECDSA P-256 私钥签名。签名文本格式为：

```text
METHOD
/path
?raw=query
nonce
```

说明：

- `METHOD` 使用大写，例如 `POST`。
- 第二行为 URL path；没有 path 时使用 `/`。
- 只有存在 query string 时才包含第三行，且保留原始 query。
- 最后一行为随机 nonce。

签名过程：

1. 将签名文本按 UTF-8 编码。
2. 对文本执行 SHA-256。
3. 使用 ECDSA P-256 对摘要生成 ASN.1/DER 签名。
4. 将签名、nonce 和公钥写入请求头。

请求头包括：

| Header | 说明 |
| --- | --- |
| `Content-Type` | 固定为 `application/json` |
| `X-Nonce` | 每次请求生成的随机 nonce |
| `X-Signature` | DER 签名的 hex 编码 |
| `X-Public-Key` | SubjectPublicKeyInfo DER 公钥的 hex 编码 |

## 5. 请求体格式

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

## 6. 响应格式

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

## 7. Token 统计

每次外部推理 API 请求完成后，CLI 都会输出 token 统计：

```text
外部推理 API token 统计：input=12, output=3, total=15
```

项目读取响应中的 `usage` 字段，并兼容两组字段名：

| 统计项 | 优先字段 | 兼容字段 |
| --- | --- | --- |
| 输入 token | `input_tokens` | `prompt_tokens` |
| 输出 token | `output_tokens` | `completion_tokens` |
| 总 token | `total_tokens` | 输入与输出相加 |

如果服务端没有返回对应字段，CLI 会显示：

```text
服务端未提供
```

项目不会估算或编造服务端未提供的 token 数据。

## 8. 常见失败场景

项目会在以下情况下停止生成正式报告：

| 场景 | 处理方式 |
| --- | --- |
| HTTP 非 2xx | 抛出 `Reasoning API returned HTTP ...`，并尽量附带服务端错误信息 |
| 响应不是合法 JSON | 抛出 `Reasoning API did not return valid JSON` |
| JSON 根节点不是对象 | 抛出 `Reasoning API JSON root must be an object` |
| 缺少 `items` 数组 | 抛出 `Reasoning response must contain an items array` |
| 返回未知或重复仓库 | 抛出 unknown or duplicate repository 错误 |
| 遗漏输入候选 | 抛出 omitted repositories 错误 |
| 示例场景中没有筛选出 AI 项目 | 抛出 `Reasoning API selected no AI projects` |

## 9. 安全注意事项

- 不要将真实私钥、管理 token 或其他密钥写入仓库。
- 文档、示例和配置模板中只应保留占位符。
- 私钥文件建议放在用户配置目录或安全目录，并限制文件权限。
- 自动测试使用本地 mock，不会调用真实 GitHub、外部推理 API、Resend 或 SMTP。

