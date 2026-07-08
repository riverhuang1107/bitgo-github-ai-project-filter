# Bitgo BFF API 签名接入指南

本文档面向客户端开发者，介绍如何生成签名并调用 BFF 的 7 个查询接口。

## 概述

BFF 接口分为三层权限，每层使用不同的签名方式：

| 层级 | 适用场景 | 签名方式 | 需要的密钥 |
|------|---------|---------|-----------|
| **Tier1** 主钱包 | 查看主钱包余额、交易记录、子钱包列表、所有订单 | 钱包私钥签名 | BTC/LTC/ETH 钱包私钥 |
| **Tier2** 子钱包 | 查看指定子钱包信息和订单 | 钱包私钥签名（含 money_id） | BTC/LTC/ETH 钱包私钥 |
| **Tier3** 用户 | 查看自己的消费订单 | 自定义密钥对签名 | RSA / ECDSA / Ed25519 密钥对 |

---

## Tier1：主钱包签名

适用于以下 4 个接口：

- `GET /api/bff/v1/wallet` — 获取主钱包信息
- `GET /api/bff/v1/wallet/transactions` — 获取充值交易记录
- `GET /api/bff/v1/wallet/sub-wallets` — 获取子钱包列表
- `GET /api/bff/v1/wallet/orders` — 获取主钱包订单

### 签名步骤

**第 1 步：构造待签名消息**

```
message = wallet_address
```

直接使用钱包地址作为消息内容，例如：

```
bc1prkx4mr6z6lzwpffnrfk5nh8e06uk8ajgeu58luwg8lrap8d7rzusas364z
```

**第 2 步：计算消息哈希**

```
msgHash = SHA256(message)    // 得到 32 字节哈希
```

**第 3 步：使用钱包私钥签名**

根据币种选择签名方法：

| 币种 | 地址类型 | 签名方法 | 签名长度 |
|------|---------|---------|---------|
| BTC/LTC | P2PKH / P2SH-P2WPKH / P2WPKH | `btcec/ecdsa.SignCompact` | 65 字节 `[V][R][S]` |
| BTC/LTC | P2TR (Taproot, bc1p.../ltc1p...) | `btcec/schnorr.Sign` | 64 字节 `[R][S]` |
| ETH | — | `go-ethereum/crypto.Sign` | 65 字节 `[R][S][V]` |

将签名结果进行 **Base64 编码**，得到 `signature` 字符串。

**第 4 步：构造 X-Params**

将以下 JSON 进行 **Base64 编码**，作为 `X-Params` 请求头的值：

```json
{
  "wallet_address": "bc1prkx4mr6z6lzwpffnrfk5nh8e06uk8ajgeu58luwg8lrap8d7rzusas364z",
  "signature": "<签名的Base64编码>"
}
```

> **注意**：Tier1 签名中 **不能** 包含 `money` 和 `money_id` 字段，否则请求会被拒绝（401）。

**第 5 步：发送请求**

将 Base64 编码后的 JSON 放入 `X-Params` 请求头：

```bash
curl -X GET "https://your-domain/api/bff/v1/wallet" \
  -H "X-Params: eyJ3YWxsZXRfYWRkcmVzcyI6ImJjMXBy..."
```

### Tier1 接口详细参数

#### 1. 获取主钱包信息

```
GET /api/bff/v1/wallet
```

无查询参数。

响应示例：

```json
{
  "wallet": {
    "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "balance": "99.99990000",
    "frozen": "0.00000000",
    "totalRechargeAmount": "100.00000000",
    "coinType": "ETH",
    "createdAt": "2026-06-15T08:00:00Z",
    "updatedAt": "2026-06-15T08:05:00Z"
  }
}
```

#### 2. 获取充值交易记录

```
GET /api/bff/v1/wallet/transactions?page=1&page_size=20
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20 |

响应示例：

```json
{
  "transactions": [
    {
      "id": "1",
      "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "txHash": "0xabc123def456...",
      "type": "charge",
      "coinType": "ETH",
      "priceCoin": "0.05000000",
      "priceUsd": "100.00000000",
      "description": "ETH recharge",
      "createdAt": "2026-06-15T08:00:00Z"
    }
  ],
  "total": 1
}
```

#### 3. 获取子钱包列表

```
GET /api/bff/v1/wallet/sub-wallets
```

无查询参数。

响应示例：

```json
{
  "balance": "89.99990000",
  "subWallets": [
    {
      "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "subId": "sub_wallet_001",
      "subBalance": "90.00000000",
      "subTotalAmount": "100.00000000",
      "coinType": "ETH",
      "createdAt": "2026-06-15T08:10:00Z",
      "updatedAt": "2026-06-15T08:12:00Z"
    }
  ]
}
```

#### 4. 获取主钱包订单

```
GET /api/bff/v1/wallet/orders?page=1&page_size=20
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| sub_id | string | 否 | 按子钱包 ID 筛选 |
| user_id | string | 否 | 按用户 ID 筛选 |
| category | string | 否 | 业务类别：`TOKEN`、`VPS` |
| type | string | 否 | 订单类型：`deduct`（扣费）、`refund`（退费） |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20，最大 100 |
| start_time | string | 否 | 起始时间，RFC3339 格式 |
| end_time | string | 否 | 截止时间，RFC3339 格式 |

响应示例：

```json
{
  "orders": [
    {
      "orderId": "order_20260702_002",
      "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "subId": "sub_wallet_001",
      "category": "TOKEN",
      "type": "deduct",
      "amount": "10.00000000",
      "refOrderId": "",
      "description": "子钱包扣费",
      "createdAt": "2026-07-02T10:00:00Z",
      "userId": "user_001"
    }
  ],
  "total": 1
}
```

---

## Tier2：子钱包签名

适用于以下 2 个接口：

- `GET /api/bff/v1/sub-wallet` — 获取子钱包信息
- `GET /api/bff/v1/sub-wallet/orders` — 获取子钱包订单

### 签名步骤

**第 1 步：构造待签名消息**

```
message = wallet_address + money + money_id
```

三个字段**直接拼接**，无分隔符。例如：

```
bc1prkx4mr6z6lzwpffnrfk5nh8e06uk8ajgeu58luwg8lrap8d7rzusas364z8sub_wallet_zzh-001
```

其中：
- `wallet_address` = `bc1prkx4mr6z6lzwpffnrfk5nh8e06uk8ajgeu58luwg8lrap8d7rzusas364z`
- `money` = `8`（面额）
- `money_id` = `sub_wallet_zzh-001`（子钱包业务标识）

**第 2 步：计算消息哈希并签名**

与 Tier1 相同：`SHA256(message)` → 使用钱包私钥签名 → Base64 编码。

**第 3 步：构造 X-Params**

将以下 JSON 进行 **Base64 编码**：

```json
{
  "wallet_address": "bc1prkx4mr6z6lzwpffnrfk5nh8e06uk8ajgeu58luwg8lrap8d7rzusas364z",
  "money": "8",
  "money_id": "sub_wallet_zzh-001",
  "signature": "<签名的Base64编码>"
}
```

> **注意**：Tier2 签名中 `money_id` **必须非空**，否则请求会被拒绝（401）。

**第 4 步：发送请求**

```bash
curl -X GET "https://your-domain/api/bff/v1/sub-wallet" \
  -H "X-Params: eyJ3YWxsZXRfYWRkcmVzcyI6ImJjMXBy..."
```

### Tier2 接口详细参数

#### 5. 获取子钱包信息

```
GET /api/bff/v1/sub-wallet
```

无查询参数（子钱包身份由签名中的 wallet_address + money_id 决定）。

响应示例：

```json
{
  "wallet": {
    "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    "subId": "sub_wallet_001",
    "subBalance": "90.00000000",
    "subTotalAmount": "100.00000000",
    "coinType": "ETH",
    "createdAt": "2026-06-15T08:10:00Z",
    "updatedAt": "2026-06-15T08:12:00Z"
  }
}
```

#### 6. 获取子钱包订单

```
GET /api/bff/v1/sub-wallet/orders?page=1&page_size=20
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_id | string | 否 | 按用户 ID 筛选 |
| category | string | 否 | 业务类别：`TOKEN`、`VPS` |
| type | string | 否 | 订单类型：`deduct`、`refund` |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20，最大 100 |
| start_time | string | 否 | 起始时间，RFC3339 格式 |
| end_time | string | 否 | 截止时间，RFC3339 格式 |

响应示例：

```json
{
  "orders": [
    {
      "orderId": "order_20260702_002",
      "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "subId": "sub_wallet_001",
      "category": "TOKEN",
      "type": "deduct",
      "amount": "10.00000000",
      "refOrderId": "",
      "description": "子钱包扣费",
      "createdAt": "2026-07-02T10:00:00Z",
      "userId": "user_001"
    }
  ],
  "total": 1
}
```

---

## Tier3：用户签名

适用于以下 1 个接口：

- `GET /api/bff/v1/user/orders` — 获取用户消费订单

Tier3 使用自定义密钥对签名，支持 **RSA 2048** / **ECDSA P-256** / **Ed25519** 三种密钥类型。

### 签名步骤

**第 1 步：准备密钥对**

生成或加载一对密钥（RSA / ECDSA / Ed25519）。公钥需要编码为 **PKIX（DER）格式的 hex 字符串**：

```go
// Go 示例
pubKeyBytes, _ := x509.MarshalPKIXPublicKey(publicKey)
publicKeyHex := hex.EncodeToString(pubKeyBytes)
```

```python
# Python 示例
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
pub_bytes = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
public_key_hex = pub_bytes.hex()
```

**第 2 步：生成随机 Nonce**

生成一个唯一的随机字符串用于防重放，例如使用时间戳纳秒：

```
nonce = "1720425600000000000"
```

**第 3 步：构造 X-Params**

将自定义参数 JSON 进行 **Base64 编码**：

```go
paramsJSON := `{"request":"user_orders","timestamp":"2026-07-08T10:00:00Z"}`
xParams := base64.StdEncoding.EncodeToString([]byte(paramsJSON))
```

X-Params 的 JSON 内容可自定义，不影响用户身份识别。

**第 4 步：构造待签名消息并签名**

```
message = X-Params + Nonce
```

将 Base64 编码后的 X-Params 字符串与 Nonce **直接拼接**（无分隔符），然后签名：

```
hash = SHA256(message)
```

根据密钥类型选择签名方法：

| 密钥类型 | 签名方法 | 签名长度 |
|---------|---------|---------|
| RSA 2048 | `rsa.SignPSS(privateKey, SHA256, hash, PSSOptions)` | 256 字节 |
| ECDSA P-256 | `ecdsa.SignASN1(privateKey, hash)` | ~70-72 字节 |
| Ed25519 | `ed25519.Sign(privateKey, hash)` | 64 字节 |

**第 5 步：编码签名**

签名值需要经过**双重编码**：先 Hex 编码，再 Base64 编码：

```
X-Signature = Base64( Hex( signatureBytes ) )
```

```go
// Go 示例
hexStr := hex.EncodeToString(signatureBytes)
xSignature := base64.StdEncoding.EncodeToString([]byte(hexStr))
```

```python
# Python 示例
import base64
hex_str = signature_bytes.hex()
x_signature = base64.b64encode(hex_str.encode()).decode()
```

**第 6 步：发送请求**

请求需要携带 4 个 Header：

| Header | 值 | 说明 |
|--------|---|------|
| `X-Public-Key` | 公钥的 hex 编码（PKIX DER 格式） | 用户身份标识 |
| `X-Signature` | `Base64(Hex(签名字节))` | 签名值 |
| `X-Nonce` | 随机唯一字符串 | 防重放 |
| `X-Params` | `Base64(JSON参数)` | 请求参数 |

```bash
curl -X GET "https://your-domain/api/bff/v1/user/orders?page=1&page_size=20" \
  -H "X-Public-Key: 30820122300d06092a864886f70d01010105000382010f..." \
  -H "X-Signature: NjE2MjYzNjQ2NTY2..." \
  -H "X-Nonce: 1720425600000000000" \
  -H "X-Params: eyJyZXF1ZXN0IjoidXNlcl9vcmRlcnMiLCJ0aW1lc3RhbXAiOiIyMDI2LTA3LTA4VDEwOjAwOjAwWiJ9"
```

### Tier3 接口详细参数

#### 7. 获取用户消费订单

```
GET /api/bff/v1/user/orders?page=1&page_size=20
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | string | 否 | 业务类别：`TOKEN`、`VPS` |
| type | string | 否 | 订单类型：`deduct`、`refund` |
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页数量，默认 20，最大 100 |
| start_time | string | 否 | 起始时间，RFC3339 格式 |
| end_time | string | 否 | 截止时间，RFC3339 格式 |

响应示例：

```json
{
  "orders": [
    {
      "orderId": "order_20260702_002",
      "accountId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "subId": "sub_wallet_001",
      "category": "TOKEN",
      "type": "deduct",
      "amount": "10.00000000",
      "refOrderId": "",
      "description": "子钱包扣费",
      "createdAt": "2026-07-02T10:00:00Z",
      "userId": "c371507891aed720561085fbd451b38e"
    }
  ],
  "total": 1
}
```

---

## 响应字段说明

| 字段 | 说明 |
|------|------|
| `accountId` | 账户 ID，由 `SHA256(wallet_address)` 取前 32 位十六进制生成 |
| `userId` | 用户 ID，由 `SHA256(X-Public-Key)` 取前 32 位十六进制生成 |
| `subId` | 子钱包 ID，即签名中的 `money_id` 原值 |

---

## 错误码

| HTTP 状态码 | gRPC Code | 说明 |
|------------|-----------|------|
| 401 | `UNAUTHENTICATED` | 签名验证失败、缺少必要 Header、或权限层级不匹配 |
| 500 | `INTERNAL` | 服务端内部错误 |

常见 401 原因：

- Tier1 签名中包含了 `money` 或 `money_id`（应为空）
- Tier2 签名中缺少 `money_id`（必须非空）
- Tier3 缺少 `X-Public-Key`、`X-Signature`、`X-Nonce`、`X-Params` 中的任一 Header
- 签名内容与发送的参数不一致
- 钱包地址无法从签名中恢复

---

## 完整代码示例

### Go

项目中提供了完整的签名 Demo，可直接运行生成三种签名和 curl 命令：

```bash
cd bitgo-bff-api
go run tools/sign_demo/main.go
```

修改 `tools/sign_demo/main.go` 顶部的常量配置你自己的密钥：

```go
// Tier1/Tier2：钱包配置
const privateKey = "L1XTSktRM9EUdbhPjxgY41D7NzPXGBFT9aFyonmcevAZPBQt3CEv"  // WIF 或 hex
const address = "bc1prkx4mr6z6lzwpffnrfk5nh8e06uk8ajgeu58luwg8lrap8d7rzusas364z"
const coinType = "BTC"       // BTC / LTC / ETH
const money = "8"             // 子钱包面额
const moneyID = "sub_wallet_zzh-001"  // 子钱包业务标识

// Tier3：用户密钥配置
const userKeyType = "RSA"    // RSA / ECDSA / Ed25519
const userPrivateKeyPEM = "" // 留空则自动生成新密钥对
```

### Python

```python
import hashlib
import base64
import json
import time
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, utils

# ===== Tier3 用户签名示例 (ECDSA P-256) =====

# 1. 生成密钥对
private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

# 2. 编码公钥为 hex (PKIX DER 格式)
pub_bytes = public_key.public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo
)
x_public_key = pub_bytes.hex()

# 3. 生成 nonce
nonce = str(time.time_ns())

# 4. 构造 X-Params
params_json = json.dumps({"request": "user_orders"})
x_params = base64.b64encode(params_json.encode()).decode()

# 5. 构造消息并签名
message = x_params + nonce
msg_hash = hashlib.sha256(message.encode()).digest()
signature_bytes = private_key.sign(
    msg_hash,
    ec.ECDSA(utils.Prehashed(hashes.SHA256()))
)

# 6. 编码签名: hex → base64
x_signature = base64.b64encode(signature_bytes.hex().encode()).decode()

# 7. 发送请求
resp = requests.get(
    "https://your-domain/api/bff/v1/user/orders",
    params={"page": 1, "page_size": 20},
    headers={
        "X-Public-Key": x_public_key,
        "X-Signature": x_signature,
        "X-Nonce": nonce,
        "X-Params": x_params,
    },
)
print(resp.json())
```

### JavaScript (Node.js)

```javascript
const crypto = require('crypto');

// ===== Tier3 用户签名示例 (ECDSA P-256) =====

// 1. 生成密钥对
const { privateKey, publicKey } = crypto.generateKeyPairSync('ec', {
  namedCurve: 'P-256',
});

// 2. 编码公钥为 hex (PKIX DER 格式)
const pubDer = publicKey.export({ type: 'spki', format: 'der' });
const xPublicKey = pubDer.toString('hex');

// 3. 生成 nonce
const nonce = Date.now().toString() + Math.random().toString(36).slice(2);

// 4. 构造 X-Params
const paramsJson = JSON.stringify({ request: 'user_orders' });
const xParams = Buffer.from(paramsJson).toString('base64');

// 5. 构造消息并签名
const message = xParams + nonce;
const msgHash = crypto.createHash('sha256').update(message).digest();
const signature = crypto.sign(null, msgHash, privateKey);

// 6. 编码签名: hex → base64
const xSignature = Buffer.from(signature.toString('hex')).toString('base64');

// 7. 发送请求
const url = new URL('https://your-domain/api/bff/v1/user/orders');
url.searchParams.set('page', '1');
url.searchParams.set('page_size', '20');

fetch(url, {
  headers: {
    'X-Public-Key': xPublicKey,
    'X-Signature': xSignature,
    'X-Nonce': nonce,
    'X-Params': xParams,
  },
})
  .then((res) => res.json())
  .then(console.log);
```
