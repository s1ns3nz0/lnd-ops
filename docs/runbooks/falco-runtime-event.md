# Falco runtime event

1. Confirm the alert rule, priority, namespace, Pod, container, and process from Falco and Falcosidekick. Do not copy environment variables, command arguments containing secrets, or raw wallet paths into an incident record.
2. If the rule is `LND Ops Runtime Test Event`, correlate it with an authorized `ops/verify-security` run. The marker is harmless and should appear only during the Phase 4 verification.
3. For any other shell, sensitive-path, token, host-namespace, or unexpected outbound event, inspect the Pod owner, Kubernetes events, image digest, and redacted container logs. Preserve the Falco event and relevant audit metadata.
4. Do not terminate LND, delete a Pod or PVC, close a channel, or weaken a policy automatically. Escalate wallet or node containment to the operator and use an isolated diagnostic copy when possible.
5. After remediation, verify Falco remains Ready, its modern eBPF event source is active, Falcosidekick is scraped, and `ops/phase3-acceptance` still passes.

