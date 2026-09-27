# One-shot Router P2P observer

This program checks a single public Lightning endpoint from a separate network.
It needs neither an SSH server nor an LND wallet. It generates an ephemeral key,
authenticates the requested node key through LND's pinned Brontide implementation,
exchanges Lightning `init`, emits one JSON observation and closes the connection.
It never opens a channel or sends a payment. A silent TCP listener, wrong node key
or Noise-only responder is not success.

The host CLI can issue a request and import its result. Phase 3 opens the interactive
request/import menu after forwarding verification. This binary alone does not mark
Phase 3 complete: current readiness, bound forwarding evidence and a recent imported
observation are all required. External origin remains operator-attested in the status.
Its result proves the authenticated connection from the machine running it;
it cannot independently establish that
machine's network location. `network_origin` is explicitly an operator attestation.
Run it from another internet connection, without a VPN or tunnel back to the node.
Results from the node's own LAN can exercise NAT loopback and are not outside-network
evidence. The reported local socket address may be private behind the observer's NAT.

Build using Go 1.26 or newer:

```sh
cd observer
go build -mod=readonly -o router-observer .
./router-observer --confirm 'PROBE ROUTER P2P FROM EXTERNAL NETWORK' < request.json > observation.json
```

The request format is:

```json
{
  "schema": "lnd-ops/router-p2p-request/v1",
  "nonce": "32 random bytes encoded as 64 hex characters",
  "identity": "the target's compressed 33-byte public key in hex",
  "endpoint": "numeric-public-ip:9735",
  "issued_at": 0,
  "expires_at": 0
}
```

The example is a format description, not a runnable request. Timestamps are Unix
seconds; issuance must not be future-dated and expiry must be within 30 minutes of
issuance. The observer also rejects expiration during the probe. Observer and
requesting host clocks must agree. Only numeric public IPs on TCP 9735 are accepted;
DNS resolution and selecting among changed addresses belong to the pending host
workflow. IPv6 endpoints use brackets. Requests with extra fields or documents fail.

On the Router host, from the repository root, issue a request for one numeric IP
already advertised by LND. Replace `PUBLIC_IP` with that address. The command reads
the existing testnet identity using the configured Kubernetes connection, stores
the nonce privately, and prints a ten-minute request:

```sh
ops/router-observation request --endpoint 'PUBLIC_IP:9735' > request.json
```

Transfer `request.json` to your separately connected machine, run the observer
command above there, then transfer `observation.json` back. Import before the
request expires, only if you controlled that execution and know it ran outside
the Router's LAN without a tunnel back:

```sh
ops/router-observation import --file observation.json --confirm 'IMPORT EXTERNAL ROUTER OBSERVATION'
ops/router-observation status
```

The importer compares the saved request, current LND node public key and advertised address,
responder key, protocol success flags and timestamps. Reissuing an unexpired request
for the same node/address returns the same nonce; another address must wait for
expiry. A changed node public key/address or expired request invalidates the result. A new
request does not reuse an old observation. `recent_operator_attested` remains valid
only until request expiry, at most ten minutes after issuance. Repeated imports do
not extend this lifetime. Expiry makes [Router Phase 3](../docs/phase2-router-runbook.md)
require a new external observation; it does not erase forwarding history or stop LND.
Each `status` call reads LND again and rechecks the node public key and advertised
address against the stored result. It does not initiate a new external probe.
In Phase 3, choose request creation, select an advertised address, then transfer the
displayed file to the external machine. Return with `r`, choose result import, enter
its file path and confirm the execution conditions. The screen rechecks all Router
conditions before advancing. The external machine still uses the observer command
above; automatic distribution and remote execution are not implemented.

Import validates consistency, not the authenticity of an unsigned JSON file. It
cannot detect a fabricated result from an untrusted operator. Network origin is an
explicit human attestation and is never labelled independently verified. Request
and result files contain public metadata, not wallet credentials.

The probe has a 15-second total connection/handshake/init deadline, shortened to
request expiry. Its stdout contains JSON only on success; diagnostics go to stderr
with a nonzero exit code. Do not treat an empty or partial redirected output file as
evidence. The observation contains public keys, socket address, request nonce and
timestamps, but no private key, wallet seed, password or payment data. It is not a
signed attestation and must come from an operator-controlled execution.

Tests use local TCP sockets and an isolated Brontide responder, not public nodes:

```sh
docker build -f observer/Dockerfile.test -t localhost/lnd-ops-router-observer-test observer
docker run --rm --network none localhost/lnd-ops-router-observer-test
```

Run these Docker commands from the repository root. The Go image is pinned by
digest; `go.mod` and `go.sum` lock source dependencies. Image build downloads those
dependencies, while the test container has no external network. Passing these tests
does not establish real testnet connectivity, peer policy compatibility, usable
channels, liquidity, forwarding, or address-change recovery.
