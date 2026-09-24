# Windows Phase 6 fault-to-runbook evidence

Validation completed: 2026-09-24 10:47:37 UTC  
Host: Windows 11 Home, WSL 2 Ubuntu, linux/amd64  
Runtime-tested Git revision: `c79a53d3f09121990be77522ca34a4701fd26bcd`

## Result

Phase 6 passed on the local Windows portfolio cluster. One real Lightning
failure, one Kubernetes failure, and one security event each traversed:

```text
fault injection -> metric or event -> Prometheus alert -> Alertmanager ->
versioned runbook -> recovery -> alert clear -> healthy post-check
```

The exercise used the production chart's configured alert durations. It did not
patch PrometheusRule resources or shorten a `for` interval. All injected
resources and policies returned to their pre-test operating state.

## Scenario evidence

| Class | Fault and signal | Alert and runbook | Recovery and post-check |
| --- | --- | --- | --- |
| Lightning | Internal LND peer ingress and egress were temporarily denied for the active disposable regtest channel. `lnd_channels_inactive_total` became positive at 10:32:47.629004 UTC. | `LndOpsChannelInactive` reached Prometheus and Alertmanager at 10:37:54.612508 UTC after its five-minute duration. [Channel inactive runbook](../runbooks/channel-inactive.md). | Recovery began only after both alert systems observed firing. The exact NetworkPolicy spec was restored in a `finally` path, the peers reconnected, and the channel was active at 10:37:54.962627 UTC, 350 ms after the alert observation. At 10:38:25.213112 UTC the alert was absent from both the Prometheus firing vector and Alertmanager active-alert API. The canonical NetworkPolicy hash was identical before and after. |
| Kubernetes | A digest-pinned, resource-bounded, token-free Pod deliberately exited and entered CrashLoop behavior. `kube_pod_status_ready{condition="false"}` became `1` at 10:38:50 UTC. | `LndOpsPodNotReady` reached Prometheus and Alertmanager at 10:40:01 UTC after its one-minute duration. [Pod not Ready runbook](../runbooks/pod-not-ready.md). | The fixture Pod was verified absent before creation. Only that named Pod was deleted; it was absent again at 10:40:01 UTC and the alert cleared at 10:40:31 UTC. |
| Security | The exercise used `kubectl exec` to run an authorized marker process inside the live payment collector. It did not write to Prometheus or Falcosidekick. Falco observed the process through its modern eBPF event source, and Falcosidekick's `LND Ops Runtime Test Event` counter increased at 10:41:02 UTC. | `LndOpsFalcoRuntimeEvent` reached Prometheus and Alertmanager at 10:41:32 UTC. [Falco runtime event runbook](../runbooks/falco-runtime-event.md). | No workload mutation was required. Falco was Ready `1/1` before and after, the five-minute event window expired, and at 10:46:04 UTC the alert was absent from both the Prometheus firing vector and Alertmanager active-alert API. |

## Commands and private evidence

```sh
ops/exercise-regtest
ops/verify-monitoring --profile regtest
ops/exercise-phase6-faults
ops/phase6-acceptance --acknowledge-host-encryption-deferred
```

The owner-only machine-readable records remain outside Git at
`${XDG_STATE_HOME:-$HOME/.local/state}/lnd-ops/evidence/`:

| Record | Schema | SHA-256 |
| --- | --- | --- |
| `phase6-faults-20260924T104604.329670Z.json` | `lnd-ops/phase6-faults/v1` | `d7102227fea2c2f5195d041e70f005d84b381eede674321db33b1e587f76ccf4` |
| `phase6-acceptance-20260924T104737.021353Z.json` | `lnd-ops/phase6-acceptance/v1` | `894cccde24302b2fc09f9d17205e337cb71842d7e55958d5bf58a952b4a95e7b` |

`ops/phase6-acceptance` requires operator ownership and mode `0600`, verifies
all three scenario records contain before and after state, verified alert to
runbook mapping, Prometheus and Alertmanager observation flags, signal, alert,
healthy and cleared timestamps, and the current Git revision. It then reruns
the Phase 5 acceptance gate.

In this evidence, “alert cleared” means the matching alert was absent from both
Prometheus's `ALERTS{alertstate="firing"}` result and Alertmanager's active-alert
API. No external notification receiver or retained resolved-notification
history is claimed.

## Safety and limitations

- Only disposable regtest channel availability was disrupted. Testnet channel
  traffic and wallet data were not fault targets.
- The Kubernetes fixture used a dedicated Pod name and no persistent volume.
- The Falco marker is an authorized test event. It does not demonstrate
  automated containment of an unknown malicious process.
- Windows full-volume encryption remains explicitly deferred. This portfolio
  test exception must be closed before claiming production readiness or using
  mainnet funds.
