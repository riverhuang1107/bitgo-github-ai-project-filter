package main

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"math/big"
	"testing"
)

func TestSignLTC(t *testing.T) {
	signature, digest, err := signMessage("ltc", "Lexample", "10", "20260630001", testWIF(ltcMainnetWIFVersion))
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestSignBTC(t *testing.T) {
	signature, digest, err := signMessage("btc", "1example", "10", "20260630001", testWIF(btcMainnetWIFVersion))
	if err != nil {
		t.Fatal(err)
	}
	assertDigestAndSignature(t, signature, digest)
}

func TestSignETH(t *testing.T) {
	signature, digest, err := signMessage("eth", "0x0000000000000000000000000000000000000001", "10", "20260630001", testETHPrivateKey())
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
	if len(digest) != 32 {
		t.Fatalf("digest length = %d", len(digest))
	}
	decoded, err := base64.StdEncoding.DecodeString(signature)
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded) != 65 {
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

func base58CheckEncode(payload []byte) string {
	first := sha256.Sum256(payload)
	second := sha256.Sum256(first[:])
	return encodeBase58(append(payload, second[:4]...))
}

func encodeBase58(input []byte) string {
	value := new(big.Int).SetBytes(input)
	zero := big.NewInt(0)
	radix := big.NewInt(58)
	mod := new(big.Int)
	var encoded []byte

	for value.Cmp(zero) > 0 {
		value.DivMod(value, radix, mod)
		encoded = append(encoded, base58Alphabet[mod.Int64()])
	}
	for _, b := range input {
		if b != 0x00 {
			break
		}
		encoded = append(encoded, base58Alphabet[0])
	}
	for i, j := 0, len(encoded)-1; i < j; i, j = i+1, j-1 {
		encoded[i], encoded[j] = encoded[j], encoded[i]
	}
	return string(encoded)
}
