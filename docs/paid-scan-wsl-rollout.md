# Paid order diagnosis: WSL rollout

Adds the read-only paid order diagnosis to the **running** WSL k3s E2E run
(`opencti-paid-scan-e2e`, started 2026-09-28) and to the existing kagent
install.

```text
kagent Agent paid-scan-diagnosis (lndops-kagent)
  └─ MCP pod paid-scan-diagnostics (lndops-agent)
       ├─ HTTPS :8443 ──► order-diagnostics (opencti-paid-scan-e2e) ──► postgres
       └─ Kubernetes API (get/list deployments, jobs, pods, events in opencti-paid-scan-e2e)
```

Source: OpenCTI `feat/order-diagnostics` at
`ebbf24a8ba3fae2f78dbdf2e00ecc4f43168a946`, lnd-ops `feat/paid-scan-diagnosis`
at `1c33b42c441a0618ba8e6f4946e2714325adc755`. Design:
[paid-scan-diagnosis.md](paid-scan-diagnosis.md).

## What changes

| Where | Change |
|---|---|
| `opencti-paid-scan-e2e` | **New** Service, NetworkPolicy, Deployment `order-diagnostics`; **new** Secret `order-diagnostics-server`; **new** Role/RoleBinding `paid-scan-workload-reader` |
| `lndops-agent` | **New** paid-scan Deployment, Service, NetworkPolicies, ServiceAccount; **new** Secret `paid-scan-diagnostics-client`; ConfigMap `runbook-gateway-source` gains the file `paid_scan_diagnostics.py` |
| `lndops-kagent` | **New** Agent `paid-scan-diagnosis`, RemoteMCPServer `paid-scan-diagnostics` |
| Existing | `runbook-gateway` is restarted by `deploy-agent` (a few seconds of LND agent tool outage). Nothing else existing may change; step 7 proves it before running |
| containerd | One imported image |

No existing OpenCTI Deployment restarts. No paid order is created. No image
is pushed.

## How to run the blocks

Every step is one block that runs in its own `bash` subshell:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
...
STEP
```

A failed command ends only that block and prints the error; your terminal
stays open. A block is safe to rerun unless it says otherwise. **STOP** means:
change nothing else and paste the output for review. Values you must fill in
are shell variables set at the top of a block (for example `T=''`); the block
refuses to run while they are empty.

Assumptions from the 2026-09-28 run: node `desktop-tjq5clv`, old checkout
`/home/miata/opencti-native-amd64-a3418ee29b9a/repo`, 13 existing OpenCTI
Deployments. Step 2 verifies each one.

## 0. Handoff folder

Copy the folder `diagnostics-image-20260929` to `~/handoff/diagnostics-20260929`
in WSL. It contains no secrets.

| File | Purpose |
|---|---|
| `opencti-diagnostics-amd64-20260929.tar.gz` | linux/amd64 image `opencti-paid-scan-e2e-api:diagnostics-20260929`, built from `ebbf24a8` only |
| `image-id.txt` | Expected image ID `sha256:3f578ab3b044550102bf114ce59787505e38981545c50793dc4d09f4236d32e4` |
| `opencti.bundle`, `lnd-ops.bundle` | Git bundles of the two branches |
| `paid-scan-wsl-rollout.md` | This runbook |
| `SHA256SUMS` | Checksums of every file above |

## 1. Environment file and clones (no cluster change)

Set `KUBECONFIG` to the kubeconfig you used for the 2026-09-28 run first.

```bash
bash -euo pipefail <<'STEP'
: "${KUBECONFIG:?Set KUBECONFIG to the existing WSL kubeconfig first}"
umask 077
cat > ~/paid-scan-diag.env <<ENV
export KUBECONFIG=$KUBECONFIG
export CTX=$(kubectl config current-context)
export H=~/handoff/diagnostics-20260929
export OLD_REPO=/home/miata/opencti-native-amd64-a3418ee29b9a/repo
export OLD_RUN=\$OLD_REPO/infra/mvp/.runtime/wsl-20a527d0b44e446780ae8616a3214eb4
export WORK=~/paid-scan-diag-20260929
export RUN=\$WORK/run
export P=~/.local/state/lnd-ops/paid-scan-diagnostics
export NS=opencti-paid-scan-e2e
export IMG=opencti-paid-scan-e2e-api:diagnostics-20260929
k=(kubectl --context "\$CTX"); kn=("\${k[@]}" -n "\$NS")
ka=("\${k[@]}" -n lndops-agent); kk=("\${k[@]}" -n lndops-kagent)
pick() {  # pick FILE KIND/NAME... : print only those documents, fail if any is missing
  python3 - "\$@" <<'PY'
import sys, yaml
path, wanted = sys.argv[1], set(sys.argv[2:])
docs = [d for d in yaml.safe_load_all(open(path)) if d]
out = [d for d in docs if f'{d["kind"]}/{d["metadata"]["name"]}' in wanted]
assert {f'{d["kind"]}/{d["metadata"]["name"]}' for d in out} == wanted, "missing object"
print(yaml.safe_dump_all(out, sort_keys=False), end="")
PY
}
ENV
source ~/paid-scan-diag.env
echo "Context: $CTX"
(cd "$H" && sha256sum --check SHA256SUMS)
mkdir -p "$RUN/evidence"
[ -d "$WORK/opencti" ] || git clone -q -b feat/order-diagnostics "$H/opencti.bundle" "$WORK/opencti"
[ -d "$WORK/lnd-ops" ] || git clone -q -b feat/paid-scan-diagnosis "$H/lnd-ops.bundle" "$WORK/lnd-ops"
test "$(git -C "$WORK/opencti" rev-parse HEAD)" = ebbf24a8ba3fae2f78dbdf2e00ecc4f43168a946
test "$(git -C "$WORK/lnd-ops" rev-parse HEAD)" = 1c33b42c441a0618ba8e6f4946e2714325adc755
python3 -c 'import yaml'
echo "STEP 1 OK"
STEP
```

**Success:** every checksum line says `OK`, the printed context is the one you
used on 2026-09-28, and the block ends with `STEP 1 OK`.

## 2. Preflight (read-only)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${k[@]}" get node desktop-tjq5clv
ls "$OLD_RUN/image-map.json" "$OLD_RUN/addresses.json" "$OLD_RUN/run-id" >/dev/null
ls ~/.local/state/lnd-ops/phase7-ollama.json >/dev/null
"${kk[@]}" get modelconfig default-model-config >/dev/null
"${kn[@]}" get deployments -o json | python3 -c '
import json, sys
items = json.load(sys.stdin)["items"]
bad = [d["metadata"]["name"] for d in items if (d["status"].get("readyReplicas") or 0) < (d["spec"].get("replicas") or 0)]
print(len(items), "deployments; not ready:", bad)
assert len(items) == 13 and not bad, "expected 13 ready deployments"'
# Record existing Deployments to prove later that none changed.
"${kn[@]}" get deployments -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.generation}{"\n"}{end}' > "$RUN/deployments.before"
for o in deploy/order-diagnostics svc/order-diagnostics networkpolicy/order-diagnostics-boundary secret/order-diagnostics-server; do
  ! "${kn[@]}" get "$o" >/dev/null 2>&1 || { echo "exists already: $o"; exit 1; }
done
! "${ka[@]}" get secret paid-scan-diagnostics-client >/dev/null 2>&1 || { echo "client secret exists already"; exit 1; }
# No existing NetworkPolicy may restrict ingress to postgres.
"${kn[@]}" get networkpolicy -o json | python3 -c '
import json, sys
hits = [p["metadata"]["name"] for p in json.load(sys.stdin)["items"]
        if p["spec"]["podSelector"].get("matchLabels", {}).get("app.kubernetes.io/name") == "postgres"]
assert not hits, f"postgres has ingress policies: {hits}"'
echo "STEP 2 OK"
STEP
```

**Success:** `13 deployments; not ready: []`, then `STEP 2 OK`. **STOP** on
anything else. A not-ready Deployment has to be fixed first so later failures
can be attributed. An existing `order-diagnostics` object means an earlier
attempt left something behind.

## 3. Import the image (sudo)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
gzip -dc "$H/opencti-diagnostics-amd64-20260929.tar.gz" |
  sudo k3s ctr -n k8s.io images import --platform linux/amd64 -
sudo k3s ctr -n k8s.io images ls -q | grep -F "$IMG"
got=$(sudo k3s crictl inspecti -o json "docker.io/library/$IMG" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"]["id"])')
want=$(tr -d '[:space:]' < "$H/image-id.txt")
echo "k3s: $got"; echo "mac: $want"
test "$got" = "$want"
echo "STEP 3 OK: k3s has exactly the image built on the Mac"
STEP
```

**Success:** the two IDs are equal and the block prints `STEP 3 OK`. A tag
alone can point anywhere; the matching ID proves the content is identical.

## 4. Service and NetworkPolicy

The renderer needs every Service's address before it renders Deployments, so
the Service comes first. `phase1` needs no maps. The renderer strips any fixed
`clusterIP`, so Kubernetes assigns one.

### 4a. Render and review (no change)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/opencti"
python3 infra/mvp/render-wsl.py --phase phase1 --output-dir "$RUN/rendered-phase1"
pick "$RUN/rendered-phase1/phase1-infrastructure.yaml" \
  Service/order-diagnostics NetworkPolicy/order-diagnostics-boundary > "$RUN/network.yaml"
cat "$RUN/network.yaml"
STEP
```

**Review:**

- The NetworkPolicy's `podSelector` is exactly
  `app.kubernetes.io/name: order-diagnostics`. A broader selector would
  restrict existing pods.
- Ingress has **one** `from` item containing both
  `namespaceSelector … lndops-agent` and `podSelector … paid-scan-diagnostics`,
  on port 8443.
- Egress allows only DNS to kube-system (53) and postgres (5432).

### 4b. Create

`create` fails instead of overwriting if the object already exists.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" create -f "$RUN/network.yaml"
"${kn[@]}" get svc order-diagnostics -o jsonpath='{.spec.clusterIP}' > "$RUN/order-diagnostics.ip"
echo "Service IP: $(cat "$RUN/order-diagnostics.ip")"
STEP
```

**Success:** two `created` lines and a Service IP.

## 5. Render the Deployment against copies of the old maps (no change)

The 2026-09-28 files are copied; the originals are not edited.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/opencti"
cp "$OLD_RUN/image-map.json" "$OLD_RUN/addresses.json" "$RUN/"
python3 - "$RUN" "$IMG" <<'PY'
import ipaddress, json, sys
from pathlib import Path
run, img = Path(sys.argv[1]), sys.argv[2]
a = json.loads((run / "addresses.json").read_text())
ip = (run / "order-diagnostics.ip").read_text().strip()
assert ipaddress.ip_address(ip).version == 4 and "order-diagnostics" not in a["services"]
a["services"]["order-diagnostics"] = ip
(run / "addresses.json").write_text(json.dumps(a, indent=2) + "\n")
i = json.loads((run / "image-map.json").read_text())
assert img not in i
i[img] = img  # local tag, as on 2026-09-28; content was verified in step 3
(run / "image-map.json").write_text(json.dumps(i, indent=2) + "\n")
PY
diff "$OLD_RUN/addresses.json" "$RUN/addresses.json" || true
diff "$OLD_RUN/image-map.json" "$RUN/image-map.json" || true
python3 infra/mvp/render-wsl.py --phase all --output-dir "$RUN/rendered" \
  --image-map "$RUN/image-map.json" --address-map "$RUN/addresses.json" \
  --run-id "$(cat "$OLD_RUN/run-id")"
pick "$RUN/rendered/phase3-applications.yaml" Deployment/order-diagnostics > "$RUN/deployment.yaml"
grep -nE 'image:|envFrom|key: ' "$RUN/deployment.yaml"
STEP
```

**Success:**

- Each `diff` shows only the new entry. JSON also adds a comma to the line
  above it.
- The render succeeds.
- `deployment.yaml` shows the image `opencti-paid-scan-e2e-api:diagnostics-20260929` and no `envFrom`.
- Its `key:` lines are exactly `CONTROL_DATABASE_DSN`, `TENANT_DATABASE_HOST`,
  `TENANT_DATABASE_PORT`, `TENANT_SECRET_DIR` and the four file keys
  `tls.crt`, `tls.key`, `token.sha256`, `tenants.allowlist`.

**STOP** on a render error like `service address map mismatch` or `unknown
source images`. It means the committed manifests differ from the 2026-09-28
checkout. That needs review, not a hand edit.

## 6. Credentials

### 6a. List tenants (read-only)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" exec deploy/postgres -- \
  psql -U scan_admin -d scan_control -Atc "select id, database_name, created_at from tenants order by created_at"
STEP
```

`psql` runs inside the postgres container over its local socket as the admin
user. This namespace is the E2E environment: every tenant here was created by
its provisioning Job. Allowlist all listed IDs.

### 6b. Generate and review

`provision-paid-scan-diagnostics` writes two Secret manifests to `$P`
(`~/.local/state/lnd-ops/paid-scan-diagnostics`, mode 0700). It applies nothing.
The agent chart only references the client Secret; it never creates it.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
TENANTS=''   # paste the tenant IDs from 6a, separated by spaces
test -n "$TENANTS"
args=(); for t in $TENANTS; do args+=(--tenant "$t"); done
"$WORK/lnd-ops/ops/provision-paid-scan-diagnostics" "${args[@]}"
python3 - "$P" <<'PY'  # shows names and keys only, never values
import json, sys
from pathlib import Path
for f in sorted(Path(sys.argv[1]).glob("*.json")):
    d = json.loads(f.read_text())
    print(f.name, d["metadata"]["namespace"], d["metadata"]["name"], sorted(d["data"]))
PY
STEP
```

**Success:** exactly these two lines:

```text
order-diagnostics-server.secret.json opencti-paid-scan-e2e order-diagnostics-server ['tenants.allowlist', 'tls.crt', 'tls.key', 'token.sha256']
paid-scan-diagnostics-client.secret.json lndops-agent paid-scan-diagnostics-client ['ca.crt', 'token']
```

Never `cat` these files or paste them anywhere.

### 6c. Create the Secrets

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${k[@]}" create -f "$P/order-diagnostics-server.secret.json" -f "$P/paid-scan-diagnostics-client.secret.json"
STEP
```

**Success:** two `created` lines. `create` refuses to overwrite an existing
Secret.

## 7. Start order-diagnostics

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" create -f "$RUN/deployment.yaml"
"${kn[@]}" rollout status deploy/order-diagnostics --timeout=3m
"${kn[@]}" get deployments -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.generation}{"\n"}{end}' |
  grep -v '^order-diagnostics ' | diff "$RUN/deployments.before" -
echo "STEP 7 OK: order-diagnostics ready; the 13 existing Deployments are unchanged"
STEP
```

**Success:** `STEP 7 OK`. An unchanged `generation` proves that no existing
Deployment spec changed.

If the rollout times out, run
`bash -c 'source ~/paid-scan-diag.env; "${kn[@]}" describe pod -l app.kubernetes.io/name=order-diagnostics; "${kn[@]}" logs deploy/order-diagnostics'`.
A `KeyError` or TLS error at startup means a Secret key or mount mismatch.

## 8. kagent side

`ops/deploy-agent` reapplies the whole agent chart, rewrites two ConfigMaps
from files and restarts `runbook-gateway`. The live LND agent may run code
that isn't on this branch, for example uncommitted Router work, and a full
reapply would silently revert it. So **8a** proves that the only differences
are the paid-scan additions.

### 8a. Change gate (read-only)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/lnd-ops"
helm --kube-context "$CTX" -n lndops-agent get values lnd-ops-agent -o yaml > "$RUN/agent-live-values.yaml"
helm --kube-context "$CTX" -n lndops-agent get manifest lnd-ops-agent > "$RUN/agent-live.yaml"
helm template lnd-ops-agent charts/agent -n lndops-agent \
  -f "$RUN/agent-live-values.yaml" -f charts/agent/paid-scan-wsl-e2e.values.yaml > "$RUN/agent-new.yaml"
"${ka[@]}" get configmap runbook-gateway-source -o json > "$RUN/cm-source.json"
"${ka[@]}" get configmap runbook-agent-runbooks -o json > "$RUN/cm-runbooks.json"
python3 - "$RUN" <<'PY'
import json, sys, yaml
from pathlib import Path
run = Path(sys.argv[1])
def objs(p):
    return {(d["kind"], d["metadata"].get("namespace", "lndops-agent"), d["metadata"]["name"]): d
            for d in yaml.safe_load_all(p.read_text()) if d}
live, new = objs(run / "agent-live.yaml"), objs(run / "agent-new.yaml")
allowed_new = {("ServiceAccount", "lndops-agent", "paid-scan-diagnostics"),
    ("Role", "opencti-paid-scan-e2e", "paid-scan-workload-reader"),
    ("RoleBinding", "opencti-paid-scan-e2e", "paid-scan-workload-reader"),
    ("Deployment", "lndops-agent", "paid-scan-diagnostics"), ("Service", "lndops-agent", "paid-scan-diagnostics"),
    ("NetworkPolicy", "lndops-agent", "paid-scan-diagnostics"),
    ("NetworkPolicy", "lndops-kagent", "kagent-paid-scan-diagnostics"),
    ("RemoteMCPServer", "lndops-kagent", "paid-scan-diagnostics"), ("Agent", "lndops-kagent", "paid-scan-diagnosis")}
changed = sorted(k for k in live if k in new and live[k] != new[k])
removed = sorted(k for k in live if k not in new)
added = set(new) - set(live)
print("added:", sorted(added)); print("changed:", changed); print("removed:", removed)
assert not changed and not removed and added == allowed_new, "chart would change existing objects"
src = json.loads((run / "cm-source.json").read_text())["data"]
branch_gw = Path("agent/runbook_gateway.py").read_text()
assert src.get("runbook_gateway.py") == branch_gw, "live runbook_gateway.py differs from this branch"
books = json.loads((run / "cm-runbooks.json").read_text())["data"]
for name, text in books.items():
    assert Path("docs/runbooks", name).read_text() == text, f"live runbook differs: {name}"
assert set(books) == {"channel-inactive.md", "pod-not-ready.md", "falco-runtime-event.md"}, f"live runbooks: {sorted(books)}"
print("GATE OK: only paid-scan objects are added; live gateway code and runbooks match this branch")
PY
STEP
```

**Success:** `GATE OK` with 9 `added` objects, and `changed` and `removed` both
empty. **STOP** otherwise. The usual cause is live Router work
(`runbook_gateway.py`, `kagent.yaml` or extra runbooks) that this branch
doesn't contain. That work has to be committed onto this branch first.

### 8b. Deploy

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/lnd-ops"
ops/deploy-agent --agent-values charts/agent/paid-scan-wsl-e2e.values.yaml
"${ka[@]}" rollout status deploy/paid-scan-diagnostics --timeout=3m
"${kk[@]}" get agent/paid-scan-diagnosis remotemcpserver/paid-scan-diagnostics
"${kn[@]}" get role/paid-scan-workload-reader rolebinding/paid-scan-workload-reader
STEP
```

**Success:** a line starting `OK Phase 7 agent deployed: kagent=0.9.12
provider=Ollama model=`, followed by the rollout completing and all four
objects being listed.

## 9. Acceptance

### 9a. Direct tool calls (no LLM)

The MCP server answers stateless JSON-RPC `tools/call` requests. The existing
`ops/exercise-phase7-agent` uses the same call. First, find a finished order
in one tenant database from 6a:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
DB=''   # a database_name from 6a
test -n "$DB"
"${kn[@]}" exec deploy/postgres -- psql -U scan_admin -d "$DB" -Atc \
  "select o.id, o.state, s.state from orders o left join scans s on s.order_id = o.id order by o.created_at desc limit 5"
STEP
```

Pick a row whose third column (scan state) is `completed`. Then:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
T=''   # tenant id of that database
O=''   # order id with scan state completed
test -n "$T" && test -n "$O"
tool() {
  "${ka[@]}" exec deploy/paid-scan-diagnostics -c gateway -- python3 -c '
import json, sys, urllib.request
p = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": sys.argv[1], "arguments": json.loads(sys.argv[2])}}).encode()
r = urllib.request.Request("http://127.0.0.1:8080/mcp", data=p, method="POST",
    headers={"Content-Type": "application/json", "Accept": "application/json"})
print(json.dumps(json.loads(json.load(urllib.request.urlopen(r, timeout=30))["result"]["content"][0]["text"]), indent=2))
' "$1" "$2"
}
echo "== 1 completed order";   tool diagnose_paid_order "{\"tenant_id\":\"$T\",\"order_id\":\"$O\"}" | tee "$RUN/evidence/9a-1.json"
echo "== 3 unknown order";     tool diagnose_paid_order "{\"tenant_id\":\"$T\",\"order_id\":\"00000000-0000-4000-8000-000000000000\"}" | tee "$RUN/evidence/9a-3.json"
echo "== 3b unknown tenant";   tool diagnose_paid_order "{\"tenant_id\":\"00000000-0000-4000-8000-000000000001\",\"order_id\":\"$O\"}" | tee "$RUN/evidence/9a-3b.json"
echo "== W workload";          tool get_opencti_workload_status '{}' | tee "$RUN/evidence/9a-w.json"
echo "== 4 endpoint down"
trap '"${kn[@]}" scale deploy/order-diagnostics --replicas=1 >/dev/null; "${kn[@]}" rollout status deploy/order-diagnostics --timeout=3m' EXIT
"${kn[@]}" scale deploy/order-diagnostics --replicas=0
"${kn[@]}" wait --for=delete pod -l app.kubernetes.io/name=order-diagnostics --timeout=2m || true
tool diagnose_paid_order "{\"tenant_id\":\"$T\",\"order_id\":\"$O\"}" | tee "$RUN/evidence/9a-4.json"
STEP
```

| # | Expected |
|---|---|
| 1 | `order_state: paid`, `scan_state: completed`, `result_recorded: true`, and `observed_at` within the last 30 seconds |
| 3, 3b | Identical output: `status: unknown` with reason `not_found_or_not_visible` |
| W | `status: observed`, 14 Deployments including `order-diagnostics`, and no `message` field anywhere |
| 4 | `status: unknown` and never a stage. The block then scales back to 1 automatically, even on failure |

Scenario 2 (the dispatcher stopped while a new order is paid) needs a new
paid run, which the 2026-09-28 scope excludes. It is deferred.

### 9b. Ask the agent

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
T=''; O=''   # same values as 9a
test -n "$T" && test -n "$O"
"${kk[@]}" port-forward service/kagent-controller 18083:8083 >/dev/null 2>&1 &
trap 'kill $! 2>/dev/null' EXIT
for i in $(seq 30); do curl -s -o /dev/null http://127.0.0.1:18083/ 2>/dev/null && break; sleep 1; done
"$WORK/lnd-ops/ops/kagent-cli" --kagent-url http://127.0.0.1:18083 --namespace lndops-kagent \
  invoke --agent paid-scan-diagnosis --timeout 8m \
  --task "Diagnose tenant $T order $O. Confirm the scanner Job state." | tee "$RUN/evidence/9b-agent.txt"
STEP
```

**Check the answer against `9a-1.json`:**

- It says the scan completed and the result was recorded.
- It quotes an `observed_at` value.
- It calls `get_opencti_workload_status` for the Job.
- It claims **no fault**, because everything is healthy.

Any claim not supported by the tool output is a finding. Write it down; don't
fix it on the cluster.

## Rollback (new objects only)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" delete deploy/order-diagnostics svc/order-diagnostics networkpolicy/order-diagnostics-boundary secret/order-diagnostics-server --ignore-not-found
(cd "$WORK/lnd-ops" && ops/deploy-agent)   # no --agent-values: paidScan disabled, paid-scan objects removed
"${ka[@]}" delete secret paid-scan-diagnostics-client --ignore-not-found
STEP
```

Run the 8a gate before rolling back too. It must pass for the same reason.
The imported image is inert. To remove it, run
`sudo k3s ctr -n k8s.io images rm docker.io/library/opencti-paid-scan-e2e-api:diagnostics-20260929`.
Delete `~/.local/state/lnd-ops/paid-scan-diagnostics/` once the credentials
are no longer needed.
