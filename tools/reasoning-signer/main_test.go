package main

import (
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

func TestSignLTC(t *testing.T) {
	signature, digest, err := signMessage("ltc", "Lexample", "10", "20260630001", testWIF(ltcMainnetWIFVersion))
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestSignLTCTaprootUsesSchnorr(t *testing.T) {
	signature, digest, err := signMessage("ltc", "ltc1pexample", "10", "20260630001", testWIF(ltcMainnetWIFVersion))
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignatureSize(t, signature, digest, 64)
}

func TestSignBTC(t *testing.T) {
	signature, digest, err := signMessage("btc", "1example", "10", "20260630001", testWIF(btcMainnetWIFVersion))
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestSignBTCTaprootUsesSchnorr(t *testing.T) {
	wif := testWIF(btcMainnetWIFVersion)
	signature, digest, err := signMessage("btc", "bc1pexample", "10", "20260630001", wif)
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignatureSize(t, signature, digest, 64)

	untweakedSignature, _, err := signWIFSchnorr(digest, wif, btcMainnetWIFVersion, false)
	if err != nil {
		t.Fatal(err)
	}
	if signature == untweakedSignature {
		t.Fatal("expected BTC Taproot signature to use tweaked private key")
	}
}

func TestSignETH(t *testing.T) {
	signature, digest, err := signMessage("eth", "0x0000000000000000000000000000000000000001", "10", "20260630001", testETHPrivateKey())
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestGenerateLTCWalletCanSign(t *testing.T) {
	wallet, err := generateWallet("ltc")
	if err != nil {
		t.Fatal(err)
	}
	if wallet.Chain != "ltc" {
		t.Fatalf("chain = %q", wallet.Chain)
	}
	if wallet.WalletAddress == "" || wallet.WalletAddress[0] != 'L' {
		t.Fatalf("unexpected LTC wallet address: %q", wallet.WalletAddress)
	}
	signature, digest, err := signMessage("ltc", wallet.WalletAddress, "10", "id", wallet.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestGenerateBTCWalletCanSign(t *testing.T) {
	wallet, err := generateWallet("btc")
	if err != nil {
		t.Fatal(err)
	}
	if wallet.Chain != "btc" {
		t.Fatalf("chain = %q", wallet.Chain)
	}
	if wallet.WalletAddress == "" || wallet.WalletAddress[0] != '1' {
		t.Fatalf("unexpected BTC wallet address: %q", wallet.WalletAddress)
	}
	signature, digest, err := signMessage("btc", wallet.WalletAddress, "10", "id", wallet.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestGenerateETHWalletCanSign(t *testing.T) {
	wallet, err := generateWallet("eth")
	if err != nil {
		t.Fatal(err)
	}
	if wallet.Chain != "eth" {
		t.Fatalf("chain = %q", wallet.Chain)
	}
	if !strings.HasPrefix(wallet.WalletAddress, "0x") {
		t.Fatalf("unexpected ETH wallet address: %q", wallet.WalletAddress)
	}
	signature, digest, err := signMessage("eth", wallet.WalletAddress, "10", "id", wallet.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestUnsupportedChain(t *testing.T) {
	_, _, err := signMessage("doge", "addr", "10", "id", testWIF(btcMainnetWIFVersion))
	if err == nil {
		t.Fatal("expected unsupported chain error")
	}
}

func TestSignedParamsJSON(t *testing.T) {
	output := signedParams{
		WalletAddress: "addr",
		Money:         "10",
		MoneyID:       "id",
		Signature:     "sig",
	}
	data, err := json.Marshal(output)
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]string
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"wallet_address", "money", "money_id", "signature"} {
		if decoded[field] == "" {
			t.Fatalf("missing field %s", field)
		}
	}
}

func assertDigestAndSignature(t *testing.T, signature string, digest [32]byte) {
	t.Helper()
	assertDigestAndSignatureSize(t, signature, digest, 65)
}

func assertDigestAndSignatureSize(t *testing.T, signature string, digest [32]byte, expectedSize int) {
	t.Helper()
	if len(digest) != 32 {
		t.Fatalf("digest length = %d", len(digest))
	}
	decoded, err := base64.StdEncoding.DecodeString(signature)
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded) != expectedSize {
		t.Fatalf("signature length = %d", len(decoded))
	}
}

func testWIF(version byte) string {
	key := make([]byte, 32)
	key[31] = 1
	payload := append([]byte{version}, key...)
	payload = append(payload, 0x01)
	return base58CheckEncode(payload)
}

func testETHPrivateKey() string {
	return "0000000000000000000000000000000000000000000000000000000000000001"
}
