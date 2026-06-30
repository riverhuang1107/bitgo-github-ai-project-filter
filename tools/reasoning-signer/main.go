package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math/big"
	"os"
	"strings"

	"github.com/btcsuite/btcd/btcec/v2"
	btcEcdsa "github.com/btcsuite/btcd/btcec/v2/ecdsa"
	ethCrypto "github.com/ethereum/go-ethereum/crypto"
)

const (
	btcMainnetWIFVersion = byte(0x80)
	ltcMainnetWIFVersion = byte(0xb0)
	base58Alphabet       = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
)

type signedParams struct {
	WalletAddress     string `json:"wallet_address"`
	Money             string `json:"money"`
	MoneyID           string `json:"money_id"`
	Signature         string `json:"signature"`
	MessageSHA256Hex  string `json:"message_sha256_hex,omitempty"`
	MessageSHA256Size int    `json:"message_sha256_size,omitempty"`
}

func main() {
	chain := flag.String("chain", "ltc", "wallet chain: ltc, btc, or eth")
	walletAddress := flag.String("wallet-address", "", "wallet address")
	money := flag.String("money", "", "money amount")
	moneyID := flag.String("money-id", "", "money id")
	privateKey := flag.String("private-key", "", "WIF private key for ltc/btc or hex private key for eth")
	includeDebug := flag.Bool("debug", false, "include digest metadata in the JSON output")
	flag.Parse()

	if strings.TrimSpace(*walletAddress) == "" || strings.TrimSpace(*money) == "" || strings.TrimSpace(*moneyID) == "" {
		fail("wallet-address, money, and money-id are required")
	}
	if strings.TrimSpace(*privateKey) == "" {
		fail("private-key is required")
	}

	signature, digest, err := signMessage(*chain, *walletAddress, *money, *moneyID, *privateKey)
	if err != nil {
		fail(err.Error())
	}

	output := signedParams{
		WalletAddress: *walletAddress,
		Money:         *money,
		MoneyID:       *moneyID,
		Signature:     signature,
	}
	if *includeDebug {
		output.MessageSHA256Hex = hex.EncodeToString(digest[:])
		output.MessageSHA256Size = len(digest)
	}

	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(output); err != nil {
		fail(err.Error())
	}
}

func signMessage(chain, walletAddress, money, moneyID, privateKey string) (string, [32]byte, error) {
	message := []byte(walletAddress + money + moneyID)
	digest := sha256.Sum256(message)

	switch strings.ToLower(strings.TrimSpace(chain)) {
	case "ltc":
		return signWIF(digest, privateKey, ltcMainnetWIFVersion)
	case "btc":
		return signWIF(digest, privateKey, btcMainnetWIFVersion)
	case "eth":
		return signETH(digest, privateKey)
	default:
		return "", digest, fmt.Errorf("unsupported chain %q; expected ltc, btc, or eth", chain)
	}
}

func signWIF(digest [32]byte, privateKeyWIF string, expectedVersion byte) (string, [32]byte, error) {
	keyBytes, compressed, err := decodeMainnetWIF(privateKeyWIF, expectedVersion)
	if err != nil {
		return "", digest, err
	}

	privateKey, _ := btcec.PrivKeyFromBytes(keyBytes)
	signature := btcEcdsa.SignCompact(privateKey, digest[:], compressed)
	return base64.StdEncoding.EncodeToString(signature), digest, nil
}

func signETH(digest [32]byte, privateKeyHex string) (string, [32]byte, error) {
	privateKey, err := ethCrypto.HexToECDSA(strings.TrimPrefix(strings.TrimSpace(privateKeyHex), "0x"))
	if err != nil {
		return "", digest, fmt.Errorf("invalid Ethereum hex private key: %w", err)
	}
	signature, err := ethCrypto.Sign(digest[:], privateKey)
	if err != nil {
		return "", digest, err
	}
	return base64.StdEncoding.EncodeToString(signature), digest, nil
}

func decodeMainnetWIF(wif string, expectedVersion byte) ([]byte, bool, error) {
	decoded, err := base58CheckDecode(strings.TrimSpace(wif))
	if err != nil {
		return nil, false, err
	}
	if len(decoded) != 33 && len(decoded) != 34 {
		return nil, false, fmt.Errorf("invalid WIF payload length: %d", len(decoded))
	}
	if decoded[0] != expectedVersion {
		return nil, false, fmt.Errorf("invalid WIF version: got 0x%02x, expected 0x%02x", decoded[0], expectedVersion)
	}

	payload := decoded[1:]
	compressed := false
	if len(payload) == 33 {
		if payload[32] != 0x01 {
			return nil, false, errors.New("invalid compressed WIF marker")
		}
		payload = payload[:32]
		compressed = true
	}
	if len(payload) != 32 {
		return nil, false, fmt.Errorf("invalid private key length: %d", len(payload))
	}
	return payload, compressed, nil
}

func base58CheckDecode(input string) ([]byte, error) {
	raw, err := decodeBase58(input)
	if err != nil {
		return nil, err
	}
	if len(raw) < 5 {
		return nil, errors.New("base58check payload is too short")
	}

	payload := raw[:len(raw)-4]
	checksum := raw[len(raw)-4:]
	first := sha256.Sum256(payload)
	second := sha256.Sum256(first[:])
	if !bytes.Equal(checksum, second[:4]) {
		return nil, errors.New("base58check checksum mismatch")
	}
	return payload, nil
}

func decodeBase58(input string) ([]byte, error) {
	if input == "" {
		return nil, errors.New("base58 string is empty")
	}

	value := big.NewInt(0)
	radix := big.NewInt(58)
	for _, r := range input {
		index := strings.IndexRune(base58Alphabet, r)
		if index < 0 {
			return nil, fmt.Errorf("invalid base58 character: %q", r)
		}
		value.Mul(value, radix)
		value.Add(value, big.NewInt(int64(index)))
	}

	decoded := value.Bytes()
	leadingZeros := 0
	for _, r := range input {
		if r != '1' {
			break
		}
		leadingZeros++
	}
	if leadingZeros > 0 {
		decoded = append(bytes.Repeat([]byte{0x00}, leadingZeros), decoded...)
	}
	return decoded, nil
}

func fail(message string) {
	fmt.Fprintln(os.Stderr, "error:", message)
	os.Exit(1)
}
