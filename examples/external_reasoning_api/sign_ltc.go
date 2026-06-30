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
	"github.com/btcsuite/btcd/btcec/v2/ecdsa"
)

const (
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
	walletAddress := flag.String("wallet-address", "", "wallet address")
	money := flag.String("money", "", "money amount")
	moneyID := flag.String("money-id", "", "money id")
	privateKeyWIF := flag.String("private-key-wif", "", "Litecoin mainnet WIF private key")
	includeDebug := flag.Bool("debug", false, "include digest metadata in the JSON output")
	flag.Parse()

	if strings.TrimSpace(*walletAddress) == "" || strings.TrimSpace(*money) == "" || strings.TrimSpace(*moneyID) == "" {
		fail("wallet-address, money, and money-id are required")
	}
	if strings.TrimSpace(*privateKeyWIF) == "" {
		fail("private-key-wif is required")
	}

	signature, digest, err := signLTCMessage(*walletAddress, *money, *moneyID, *privateKeyWIF)
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

func signLTCMessage(walletAddress, money, moneyID, privateKeyWIF string) (string, [32]byte, error) {
	keyBytes, compressed, err := decodeLitecoinMainnetWIF(privateKeyWIF)
	if err != nil {
		return "", [32]byte{}, err
	}

	privateKey, _ := btcec.PrivKeyFromBytes(keyBytes)
	message := []byte(walletAddress + money + moneyID)
	digest := sha256.Sum256(message)
	signature := ecdsa.SignCompact(privateKey, digest[:], compressed)
	return base64.StdEncoding.EncodeToString(signature), digest, nil
}

func decodeLitecoinMainnetWIF(wif string) ([]byte, bool, error) {
	decoded, err := base58CheckDecode(strings.TrimSpace(wif))
	if err != nil {
		return nil, false, err
	}
	if len(decoded) != 33 && len(decoded) != 34 {
		return nil, false, fmt.Errorf("invalid WIF payload length: %d", len(decoded))
	}
	if decoded[0] != ltcMainnetWIFVersion {
		return nil, false, fmt.Errorf("invalid Litecoin mainnet WIF version: 0x%02x", decoded[0])
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
