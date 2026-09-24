# Kubernetes security baseline

This document defines the Phase 4 controls for the LND project namespaces. The threat model covers accidental Kubernetes misconfiguration and a compromised workload attempting to reach LND credentials, wallet data, the management API, or the host.

## Trust boundaries

- The host, operator account, and project kubeconfig are administrative trust boundaries.
- `lnd-regtest` and `lnd-testnet` contain wallet-bearing workloads. Their persistent volumes and in-Pod macaroons are sensitive.
- `lnd-monitoring` has cluster-wide read visibility through upstream monitoring components and remains separate from wallet namespaces.
- `kyverno` is an admission-control boundary. `falco` is a privileged node-sensor boundary. Neither namespace is selected by the LND workload policy.
- Wallet unlock, seeds, payments, channel closure, PVC deletion, SCB deletion, and policy weakening remain manual operations.

## Enforced controls

The `lnd-ops-workload-baseline` ClusterPolicy selects only namespaces labeled `lnd-ops-security=protected` and enforces:

- images from `docker.io` referenced by digest;
- CPU and memory requests and limits for every container;
- `allowPrivilegeEscalation: false` and dropping all Linux capabilities;
- `RuntimeDefault` seccomp;
- no privileged containers, host namespaces, or hostPath volumes.

The pinned upstream LND, lndmon, Bitcoin Core, and Python images currently start as UID 0. `runAsNonRoot` is therefore a documented compatibility exception. LND and the monitoring sidecars run without added capabilities. Bitcoin Core adds only `FOWNER` because its upstream entrypoint normalizes permissions on a reused local-path PVC before dropping to UID 101; all other capabilities remain dropped and privilege escalation stays disabled. Removing these exceptions requires tested non-root images and a reviewed migration of existing wallet volume ownership.

Kyverno and Falco charts are vendored with checksums. A repository Helm 4 post-renderer rewrites runtime image tags to verified multi-architecture OCI digests. The lock contains manifests supporting linux/amd64 and linux/arm64.

## Identity and authorization

- LND Pods use `lnd-node`; Bitcoin Core uses `bitcoin-node`.
- Both ServiceAccounts disable automatic token mounting.
- No RoleBinding grants them Kubernetes API access.
- lndmon and the payment collector share the LND Pod boundary and its token-free ServiceAccount. They use only the read-only macaroon mounted from the LND volume.

## Network isolation

Both wallet namespaces use default-deny ingress and egress. Explicit rules allow:

- UDP/TCP DNS to `kube-system` on port 53;
- Prometheus scrapes from the labeled monitoring namespace;
- regtest LND-to-Bitcoin RPC/ZMQ on TCP 18443, 28332, and 28333;
- regtest peer traffic inside the namespace on TCP 9735;
- testnet Lightning peer traffic on TCP 9735 and Neutrino Bitcoin traffic on TCP 18333.

The acceptance test creates a compliant disposable Pod and proves it cannot connect to LND RPC on TCP 10009. It then deletes the probe. Host firewall rules remain a separate prerequisite; no additional firewall product is installed.

## Runtime detection and certificates

Falco runs as a node DaemonSet in its privileged namespace with the modern eBPF driver. A harmless explicit marker produces a custom Falco event, which Falcosidekick exports to Prometheus and the `LndOpsFalcoRuntimeEvent` alert routes to Alertmanager.

The payment collector exports only the LND TLS certificate expiry timestamp. The 30-day alert links to a manual rotation runbook. cert-manager is not installed because LND owns this self-signed certificate and no separate in-cluster issuer or consumer contract currently exists. Introduce cert-manager only with a reviewed issuance and rotation design.

## Acceptance

Run from a clean checkout with the intended kubeconfig:

```sh
ops/deploy-security
ops/verify-security
ops/phase4-acceptance
```

The verifier performs positive and negative admission checks, RBAC denial, token-mount inspection, an actual NetworkPolicy connection attempt, Falco driver and event delivery checks, Alertmanager delivery, and live certificate-expiry validation. The Phase 4 coordinator also reruns Phase 3 continuity and writes private `0600` evidence.
