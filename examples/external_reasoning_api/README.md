# External Reasoning API Example

This directory is a standalone example for the signed `X-Params` protocol. It does not modify or import the project runtime code.

## Files

- `sign_ltc.go` decodes a Litecoin mainnet WIF private key, hashes `wallet_address + money + money_id` with `sha256.Sum256`, signs it with `github.com/btcsuite/btcd/btcec/v2/ecdsa.SignCompact`, and returns JSON.
- `request_example.py` calls the Go signer, base64-encodes the JSON params for the `X-Params` header, and optionally sends the Python HTTP request.

## Dry Run

Set the private key in an environment variable so it is not committed to the repository:

```powershell
$env:EXTERNAL_REASONING_LTC_WIF = "<your Litecoin WIF private key>"
python .\request_example.py --money YOUR_WALLET_MONEY --debug
```

The dry run validates that:

- the Go signer produced a non-empty base64 compact signature;
- the SHA-256 digest length is 32 bytes when `--debug` is used;
- the generated `X-Params` value decodes to JSON with `wallet_address`, `money`, `money_id`, and `signature`.

## Send One Example Request

```powershell
$env:EXTERNAL_REASONING_LTC_WIF = "<your Litecoin WIF private key>"
python .\request_example.py --money YOUR_WALLET_MONEY --send
```

Defaults and required inputs:

- wallet address: `MTymcTbieD5u3K8Vfsa7eHN3NZuKQzwTpk`
- money: required; use the amount provided by a person, for example `--money YOUR_WALLET_MONEY`
- money id: generated automatically as `money_<timestamp>_<random>` unless `--money-id` is provided for an existing record
- endpoint: `https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages`
- model: `deepseek-v3`
- request message: `你好`

Do not commit real private keys, generated signatures, or full request headers.
