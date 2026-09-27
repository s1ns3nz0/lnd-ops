// A one-shot Lightning identity probe. No wallet, channel or payment RPCs.
package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"time"

	"github.com/btcsuite/btcd/btcec/v2"
	"github.com/lightningnetwork/lnd/brontide"
	"github.com/lightningnetwork/lnd/keychain"
	"github.com/lightningnetwork/lnd/lnwire"
)

type request struct {
	Schema    string `json:"schema"`
	Nonce     string `json:"nonce"`
	Identity  string `json:"identity"`
	Endpoint  string `json:"endpoint"`
	IssuedAt  int64  `json:"issued_at"`
	ExpiresAt int64  `json:"expires_at"`
}

type evidence struct {
	Schema       string  `json:"schema"`
	Request      request `json:"request"`
	StartedAt    int64   `json:"started_at"`
	VerifiedAt   int64   `json:"verified_at"`
	ObserverKey  string  `json:"observer_key"`
	LocalAddress string  `json:"local_address"`
	RemoteKey    string  `json:"remote_key"`
	Handshake    bool    `json:"authenticated_handshake"`
	InitReceived bool    `json:"lightning_init_received"`
	// A cryptographic handshake proves the target key, not the physical
	// location of the probe. Do not promote this attestation into measured fact.
	NetworkOrigin string `json:"network_origin"`
}

func publicAddress(address netip.Addr) bool {
	address = address.Unmap()
	if !address.IsGlobalUnicast() || address.IsPrivate() || address.IsLoopback() || address.IsLinkLocalUnicast() {
		return false
	}
	for _, cidr := range []string{"100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4", "2001:db8::/32"} {
		if netip.MustParsePrefix(cidr).Contains(address) {
			return false
		}
	}
	return address.Zone() == ""
}

func validateRequest(r request, now int64) (*btcec.PublicKey, error) {
	if r.Schema != "lnd-ops/router-p2p-request/v1" {
		return nil, errors.New("unsupported request schema")
	}
	nonce, err := hex.DecodeString(r.Nonce)
	if err != nil || len(nonce) != 32 {
		return nil, errors.New("request nonce must be 32 bytes of hex")
	}
	if r.IssuedAt <= 0 || r.IssuedAt > now || r.ExpiresAt <= now || r.ExpiresAt-r.IssuedAt > 1800 {
		return nil, errors.New("request is future-dated, expired or exceeds 30 minutes")
	}
	endpoint, err := netip.ParseAddrPort(r.Endpoint)
	if err != nil || endpoint.Port() != 9735 || !publicAddress(endpoint.Addr()) {
		return nil, errors.New("request must select one numeric public IP on TCP 9735")
	}
	key, err := hex.DecodeString(r.Identity)
	if err != nil || len(key) != 33 {
		return nil, errors.New("invalid compressed target public key")
	}
	return btcec.ParsePubKey(key)
}

func probe(ctx context.Context, endpoint string, target *btcec.PublicKey) (*evidence, error) {
	private, err := btcec.NewPrivateKey()
	if err != nil {
		return nil, err
	}
	defer private.Zero()
	address, err := net.ResolveTCPAddr("tcp", endpoint)
	if err != nil {
		return nil, err
	}
	var stopClose func() bool
	dial := func(network, destination string, _ time.Duration) (net.Conn, error) {
		raw, err := (&net.Dialer{}).DialContext(ctx, network, destination)
		if err != nil {
			return nil, err
		}
		stopClose = context.AfterFunc(ctx, func() { _ = raw.Close() })
		return raw, nil
	}
	defer func() {
		if stopClose != nil {
			stopClose()
		}
	}()
	connection, err := brontide.Dial(&keychain.PrivKeyECDH{PrivKey: private},
		&lnwire.NetAddress{IdentityKey: target, Address: address}, 10*time.Second, dial)
	if err != nil {
		return nil, fmt.Errorf("authenticated handshake failed: %w", err)
	}
	defer connection.Close()
	// Confirm that the responder is speaking Lightning beyond Noise act two.
	if err = writeInit(connection); err != nil {
		return nil, fmt.Errorf("Lightning init write failed: %w", err)
	}
	message, err := readMessage(connection)
	if err != nil {
		return nil, fmt.Errorf("Lightning init read failed: %w", err)
	}
	if _, ok := message.(*lnwire.Init); !ok {
		return nil, errors.New("responder did not send Lightning init")
	}
	return &evidence{Schema: "lnd-ops/router-p2p-observation/v1", VerifiedAt: time.Now().Unix(),
		ObserverKey:  hex.EncodeToString(private.PubKey().SerializeCompressed()),
		LocalAddress: connection.LocalAddr().String(), RemoteKey: hex.EncodeToString(connection.RemotePub().SerializeCompressed()),
		Handshake: true, InitReceived: true}, nil
}

func writeInit(writer io.Writer) error {
	var encoded bytes.Buffer
	init := lnwire.NewInitMessage(lnwire.NewRawFeatureVector(), lnwire.NewRawFeatureVector())
	if _, err := lnwire.WriteMessage(&encoded, init, 0); err != nil {
		return err
	}
	_, err := io.Copy(writer, &encoded)
	return err
}

func readMessage(connection *brontide.Conn) (lnwire.Message, error) {
	length, err := connection.ReadNextHeader()
	if err != nil {
		return nil, err
	}
	if length > 65535+16 {
		return nil, errors.New("Lightning frame exceeds protocol limit")
	}
	body, err := connection.ReadNextBody(make([]byte, length))
	if err != nil {
		return nil, err
	}
	// Init's optional TLV decoder needs EOF at the end of this frame, not
	// the end of the entire TCP session.
	return lnwire.ReadMessage(bytes.NewReader(body), 0)
}

func run(input io.Reader, output io.Writer, confirmation string) error {
	if confirmation != "PROBE ROUTER P2P FROM EXTERNAL NETWORK" {
		return errors.New("explicit target connection and external-network confirmation required")
	}
	decoder := json.NewDecoder(io.LimitReader(input, 65537))
	decoder.DisallowUnknownFields()
	var r request
	if err := decoder.Decode(&r); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return errors.New("expected exactly one request document")
	}
	started := time.Now().Unix()
	key, err := validateRequest(r, started)
	if err != nil {
		return err
	}
	deadline := time.Now().Add(15 * time.Second)
	if expiry := time.Unix(r.ExpiresAt, 0); expiry.Before(deadline) {
		deadline = expiry
	}
	ctx, cancel := context.WithDeadline(context.Background(), deadline)
	defer cancel()
	result, err := probe(ctx, r.Endpoint, key)
	if err != nil {
		return err
	}
	if result.VerifiedAt >= r.ExpiresAt {
		return errors.New("request expired during observation")
	}
	result.Request, result.StartedAt = r, started
	result.NetworkOrigin = "operator-attested-external"
	return json.NewEncoder(output).Encode(result)
}

func main() {
	confirmation := flag.String("confirm", "", "PROBE ROUTER P2P FROM EXTERNAL NETWORK; use a separate network, without VPN back to the node")
	flag.Parse()
	if flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "read the request JSON from stdin")
		os.Exit(2)
	}
	if err := run(os.Stdin, os.Stdout, *confirmation); err != nil {
		fmt.Fprintln(os.Stderr, "P2P observation failed:", err)
		os.Exit(1)
	}
}
