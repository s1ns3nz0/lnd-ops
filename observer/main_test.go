package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"io"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/btcsuite/btcd/btcec/v2"
	"github.com/lightningnetwork/lnd/brontide"
	"github.com/lightningnetwork/lnd/keychain"
)

func listener(t *testing.T) (*brontide.Listener, *btcec.PublicKey) {
	t.Helper()
	private, err := btcec.NewPrivateKey()
	if err != nil {
		t.Fatal(err)
	}
	l, err := brontide.NewListener(&keychain.PrivKeyECDH{PrivKey: private}, "127.0.0.1:0",
		func(*btcec.PublicKey) (bool, error) { return true, nil })
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = l.Close() })
	return l, private.PubKey()
}

func TestAuthenticatedLightningInit(t *testing.T) {
	l, key := listener(t)
	done := make(chan error, 1)
	go func() {
		conn, err := l.Accept()
		if err != nil {
			done <- err
			return
		}
		defer conn.Close()
		_ = conn.SetDeadline(time.Now().Add(2 * time.Second))
		_, err = readMessage(conn.(*brontide.Conn))
		if err == nil {
			err = writeInit(conn)
		}
		done <- err
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	result, err := probe(ctx, l.Addr().String(), key)
	if err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if !result.Handshake || !result.InitReceived || result.RemoteKey != hex.EncodeToString(key.SerializeCompressed()) {
		t.Fatalf("wrong proof: %+v", result)
	}
	if result.NetworkOrigin != "" {
		t.Fatal("probe must not infer a network-origin attestation")
	}
}

func TestDifferentNodeKeyIsRejected(t *testing.T) {
	l, _ := listener(t)
	other, _ := btcec.NewPrivateKey()
	go func() {
		conn, err := l.Accept()
		if err == nil {
			_ = conn.Close()
		}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := probe(ctx, l.Addr().String(), other.PubKey()); err == nil {
		t.Fatal("wrong identity accepted")
	}
}

func TestSilentPortIsBoundedAndNotProof(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	done := make(chan struct{})
	go func() {
		defer close(done)
		conn, err := l.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = io.Copy(io.Discard, conn)
	}()
	key, _ := btcec.NewPrivateKey()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	started := time.Now()
	if _, err := probe(ctx, l.Addr().String(), key.PubKey()); err == nil {
		t.Fatal("plain TCP accepted")
	}
	if time.Since(started) > time.Second {
		t.Fatal("probe ignored total timeout")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("probe left a connection open")
	}
}

func TestRequestTargetAndLifetime(t *testing.T) {
	key, _ := btcec.NewPrivateKey()
	r := request{Schema: "lnd-ops/router-p2p-request/v1", Nonce: strings.Repeat("ab", 32),
		Identity: hex.EncodeToString(key.PubKey().SerializeCompressed()), Endpoint: "8.8.8.8:9735", IssuedAt: 100, ExpiresAt: 200}
	if _, err := validateRequest(r, 150); err != nil {
		t.Fatal(err)
	}
	// No network calls are made by request validation.
	for _, endpoint := range []string{"127.0.0.1:9735", "10.0.0.1:9735", "100.64.0.1:9735", "192.0.2.1:9735", "8.8.8.8:22", "example.org:9735", "[::1]:9735", "[2001:db8::1]:9735"} {
		bad := r
		bad.Endpoint = endpoint
		if _, err := validateRequest(bad, 150); err == nil {
			t.Fatalf("accepted %s", endpoint)
		}
	}
	for _, now := range []int64{99, 200, 201} {
		if _, err := validateRequest(r, now); err == nil {
			t.Fatal("invalid time accepted")
		}
	}
	r.ExpiresAt = 2000
	if _, err := validateRequest(r, 150); err == nil {
		t.Fatal("overlong request accepted")
	}
}

func TestCLIRejectsBeforeConnecting(t *testing.T) {
	var output bytes.Buffer
	if err := run(strings.NewReader("{}"), &output, ""); err == nil {
		t.Fatal("missing approval accepted")
	}
	for _, input := range []string{`{"unknown":true}`, `{} {}`, `{"schema":"wrong"}`} {
		if err := run(strings.NewReader(input), &output, "PROBE ROUTER P2P FROM EXTERNAL NETWORK"); err == nil {
			t.Fatal("invalid input accepted")
		}
	}
	if output.Len() != 0 {
		t.Fatal("failed request produced success evidence")
	}
}

func TestHandshakeWithoutLightningInitIsNotProof(t *testing.T) {
	l, key := listener(t)
	done := make(chan struct{})
	go func() {
		defer close(done)
		conn, err := l.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = io.Copy(io.Discard, conn)
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if _, err := probe(ctx, l.Addr().String(), key); err == nil {
		t.Fatal("Noise-only responder accepted")
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("init timeout did not close connection")
	}
}
