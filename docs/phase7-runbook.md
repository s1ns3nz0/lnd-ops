# Phase 7 constrained kagent runbook

Phase 7 connects the Kubernetes cluster to one operator-selected Ollama server.
The server may be a Mac, Windows host, Linux workstation, or dedicated GPU
server. The repository stores no machine-specific address. The deployment
command validates and records the selected endpoint in the operator's private
state directory.

## Security boundary

kagent receives no generic Kubernetes, Helm, shell, arbitrary PromQL, or LND
RPC tool. Its only tool source is `lnd-ops-runbook-gateway`, which exposes:

- allowlisted Pod, StatefulSet, PVC, and event reads;
- the final 50 redacted log lines from an allowlisted namespace;
- three fixed Prometheus diagnoses for inactive channels, unready Pods, and
  Falco runtime events;
- three versioned runbooks;
- a health verification;
- one mutation: restart the isolated `runbook-diagnostic-probe` Deployment.

The gateway cannot create or unlock a wallet, read a seed or macaroon, initiate
a payment, close a channel, modify an LND StatefulSet, delete a PVC, or weaken a
NetworkPolicy. Kubernetes RBAC denies those operations even if the model asks
for them. A denied request creates a Kubernetes Event. The one allowed restart
also creates an Event, and a five-minute cooldown rejects immediate repeats.

The kagent Agent Pod uses a token-free ServiceAccount. Only the gateway has a
Kubernetes token, scoped through namespace Roles. The UI and controller remain
ClusterIP services and are accessed through local `kubectl port-forward`.

## Prepare the Ollama server

Use a model that supports tool calling. The model name passed to the deployment
must already appear in the server's `/api/tags` response. `qwen3:8b` is the
default documented example, not a hidden fallback.

Prefer an HTTPS reverse proxy in front of Ollama:

```text
Kubernetes actor -> HTTPS reverse proxy -> 127.0.0.1:11434 Ollama
```

The reverse proxy should accept traffic only from the Kubernetes host or its
private network. Do not expose Ollama's unauthenticated port to the Internet.
The native Ollama provider in the pinned kagent release does not attach a
secret bearer header, so enforce access with a private network, VPN, and source
IP firewall rule. Use a certificate trusted by the cluster's system CA store.

For a temporary same-LAN demonstration, bind Ollama to the server's LAN address,
permit only the Kubernetes host in the host firewall, and explicitly acknowledge
HTTP when deploying. Replace this with HTTPS before using an untrusted network.

Verify from the Kubernetes host without printing model contents:

```sh
curl --fail --silent https://OLLAMA_SERVER/api/tags |
  python3 -c 'import json,sys; print([m["name"] for m in json.load(sys.stdin)["models"]])'
```

## Deploy

Choose a single host CIDR for the Ollama server. A server at `192.0.2.20` uses
`192.0.2.20/32`:

```sh
ops/deploy-agent \
  --endpoint https://ollama.example.internal \
  --model qwen3:8b \
  --server-cidr 192.0.2.20/32
```

For a temporary trusted-LAN HTTP endpoint:

```sh
ops/deploy-agent \
  --endpoint http://192.0.2.20:11434 \
  --model qwen3:8b \
  --server-cidr 192.0.2.20/32 \
  --allow-insecure-http
```

The selected endpoint, model, CIDR, and HTTP acknowledgement are written with
mode `0600` to `${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/phase7-ollama.json`.
They are configuration rather than credentials. Rerun `ops/deploy-agent`
without arguments to reuse this configuration.

The script verifies the pinned chart checksums, the Ollama `/api/tags`
response, and the requested model before changing the cluster. It then installs
kagent `0.9.12`, creates the constrained gateway, applies the egress CIDR, and
waits for both gateway Deployments.

## Exercise and acceptance

Run the full live exercise from a clean checkout:

```sh
ops/exercise-phase7-agent
ops/phase7-acceptance
```

The exercise invokes kagent through a local port-forward. The model must use the
live inactive-channel diagnostic and the versioned runbook, then return:

1. Observed facts
2. Likely cause
3. Confidence
4. Matching runbook
5. Recommended command
6. Automation eligibility

It then calls the policy gateway directly to prove the deterministic controls:
the probe restart succeeds and is audited, an immediate repeat is denied by the
cooldown, and `unlock_wallet` is denied and audited. Private response and JSON
evidence files use mode `0600`; the JSON stores only the response hash and
boolean outcomes.

Access the UI locally when needed:

```sh
kubectl -n kagent port-forward service/kagent-ui 8080:8080
```

Open `http://127.0.0.1:8080`. Stop the port-forward when the session ends.

## Failure behavior

If Ollama is unreachable, the model is absent, the MCP gateway is unaccepted,
or a tool returns an error, the deployment or exercise fails. No fallback model
or broader Kubernetes tool is enabled. The diagnostic probe is the only
mutable workload; an LLM outage cannot change the LND nodes, wallets, channels,
payments, backups, PVCs, or security policy.
