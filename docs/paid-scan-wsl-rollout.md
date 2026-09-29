# Paid-scan and L402 monitoring: WSL rollout

This runbook deploys the kagent paid-scan agent and everything it reads into
the **running** WSL k3s E2E run (`opencti-paid-scan-e2e`, started 2026-09-28).
It also sets up the evaluation fixture. It is a runbook: fixed steps, and it
stops on the first failed check.

```text
kagent Agent paid-scan-diagnosis (+ eval twin)            lndops-kagent
  └─ MCP pod paid-scan-diagnostics                         lndops-agent
       ├─ get_playbook ──────────► ConfigMap paid-scan-playbooks (git revision)
       ├─ diagnose_paid_order ───► order-diagnostics :8443 ──► postgres      opencti-paid-scan-e2e
       ├─ get_opencti_workload_status ─► Kubernetes API (get/list, one namespace)
       └─ diagnose_l402_funnel ──► Prometheus ◄── scrape ── l402-aperture :9000/metrics
                                        └─ 4 alerts (opencti-l402) → Alertmanager UI
```

## Parts and what they change

| Part | Steps | Existing objects changed |
|---|---|---|
| **A. Additive** | 1–7 | None. Only new objects, plus `runbook-gateway-source` gaining files |
| **B. Aperture metrics** | 8–10 | `l402-aperture` Deployment (new image and port; **restarts Aperture**), its Service (adds a port), ConfigMap `l402-aperture-config` (adds a `prometheus` block) |
| **C. Monitoring** | 11–12 | `lnd-ops-monitoring` Helm release (adds one scrape job), PrometheusRule `lnd-ops-infrastructure` (adds one group) |
| **D. Agent** | 13–14 | The `lnd-ops-agent` Helm release (adds paid-scan objects only; the gate proves it). `runbook-gateway` restarts, as `deploy-agent` always does |
| **E. Acceptance** | 15–16 | Scales `order-diagnostics` to 0 and back once |

Nothing here creates a paid order, pushes an image or sends data outside the
cluster. Alerts stay in the Alertmanager UI.

## How to run the blocks

Each step is one block that runs in its own subshell:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
...
STEP
```

- A failure ends only that block. Your terminal stays open, and a block is
  safe to rerun unless it says otherwise.
- **STOP** means: change nothing else and paste the output for review.
- Values you fill in are variables at the top of a block. The block refuses to
  run while they are empty.
- Parts are independent checkpoints. You can stop after any part; the system
  is consistent at every part boundary.

## 0. Handoff folder (prepared on the Mac)

Copy the folder to `~/handoff/paid-scan-20260930` in WSL. It contains no
secrets.

| File | Content |
|---|---|
| `opencti.bundle` | OpenCTI branch `feat/aperture-metrics` (order-diagnostics endpoint and Aperture metrics wiring) |
| `lnd-ops.bundle` | lnd-ops branch `feat/l402-funnel` (agent tools, playbooks, alerts, eval, this runbook) |
| `COMMITS` | Expected branch tips, e.g. `opencti <sha>` and `lnd-ops <sha>` |
| `order-diagnostics.tar.gz`, `order-diagnostics.image-id` | Image `opencti-paid-scan-e2e-api:diagnostics-20260929` |
| `aperture-metrics.tar.gz`, `aperture-metrics.image-id` | Image `opencti-payments-fixture-aperture:metrics-20260929` (upstream `311220b` plus L402 metrics, no DB migrations) |
| `paid-scan-wsl-rollout.md` | This runbook |
| `SHA256SUMS` | Checksums of every file above |

## Part A: additive

### 1. Environment and clones (no cluster change)

Set `KUBECONFIG` to the kubeconfig used for the 2026-09-28 run first.

```bash
bash -euo pipefail <<'STEP'
: "${KUBECONFIG:?Set KUBECONFIG to the existing WSL kubeconfig first}"
umask 077
cat > ~/paid-scan-diag.env <<ENV
export KUBECONFIG=$KUBECONFIG
export CTX=$(kubectl config current-context)
export H=~/handoff/paid-scan-20260930
export OLD_REPO=/home/miata/opencti-native-amd64-a3418ee29b9a/repo
export OLD_RUN=\$OLD_REPO/infra/mvp/.runtime/wsl-20a527d0b44e446780ae8616a3214eb4
export WORK=~/paid-scan-20260930
export RUN=\$WORK/run
export P=~/.local/state/lnd-ops/paid-scan-diagnostics
export NS=opencti-paid-scan-e2e
export DIAG_IMG=opencti-paid-scan-e2e-api:diagnostics-20260929
export APER_IMG=opencti-payments-fixture-aperture:metrics-20260929
k=(kubectl --context "\$CTX"); kn=("\${k[@]}" -n "\$NS")
ka=("\${k[@]}" -n lndops-agent); kk=("\${k[@]}" -n lndops-kagent); km=("\${k[@]}" -n lndops-monitoring)
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
[ -d "$WORK/opencti" ] || git clone -q -b feat/aperture-metrics "$H/opencti.bundle" "$WORK/opencti"
[ -d "$WORK/lnd-ops" ] || git clone -q -b feat/l402-funnel "$H/lnd-ops.bundle" "$WORK/lnd-ops"
test "$(git -C "$WORK/opencti" rev-parse HEAD)" = "$(awk '$1=="opencti"{print $2}' "$H/COMMITS")"
test "$(git -C "$WORK/lnd-ops" rev-parse HEAD)" = "$(awk '$1=="lnd-ops"{print $2}' "$H/COMMITS")"
python3 -c 'import yaml'
echo "STEP 1 OK"
STEP
```

**Success:** every checksum line says `OK`. The printed context is the one you
used on 2026-09-28. The block ends with `STEP 1 OK`.

### 2. Preflight (read-only)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${k[@]}" get node desktop-tjq5clv
ls "$OLD_RUN/image-map.json" "$OLD_RUN/addresses.json" "$OLD_RUN/run-id" ~/.local/state/lnd-ops/phase7-ollama.json >/dev/null
"${kk[@]}" get modelconfig default-model-config >/dev/null
# The agents need the model server. It has failed silently before (the Mac's DHCP address changed).
ENDPOINT=$(python3 -c 'import json,os; print(json.load(open(os.path.expanduser("~/.local/state/lnd-ops/phase7-ollama.json")))["endpoint"])')
curl -sk -m 5 "$ENDPOINT/api/version" | grep -q '"version"' || { echo "Ollama endpoint $ENDPOINT is not reachable from WSL"; exit 1; }
echo "Ollama reachable: $ENDPOINT"
"${kn[@]}" get deployments -o json | python3 -c '
import json, sys
items = json.load(sys.stdin)["items"]
bad = [d["metadata"]["name"] for d in items if (d["status"].get("readyReplicas") or 0) < (d["spec"].get("replicas") or 0)]
print(len(items), "deployments; not ready:", bad)
assert len(items) == 13 and not bad, "expected 13 ready deployments"'
"${kn[@]}" get deployments -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.generation}{"\n"}{end}' > "$RUN/deployments.before"
for o in deploy/order-diagnostics svc/order-diagnostics networkpolicy/order-diagnostics-boundary secret/order-diagnostics-server; do
  ! "${kn[@]}" get "$o" >/dev/null 2>&1 || { echo "exists already: $o"; exit 1; }
done
! "${ka[@]}" get secret paid-scan-diagnostics-client >/dev/null 2>&1 || { echo "client secret exists already"; exit 1; }
"${kn[@]}" get networkpolicy -o json | python3 -c '
import json, sys
hits = [p["metadata"]["name"] for p in json.load(sys.stdin)["items"]
        if p["spec"]["podSelector"].get("matchLabels", {}).get("app.kubernetes.io/name") in ("postgres", "l402-aperture")]
assert not hits, f"unexpected ingress policies: {hits}"'
echo "STEP 2 OK"
STEP
```

**Success:** `Ollama reachable: …`, `13 deployments; not ready: []`, then
`STEP 2 OK`. If Ollama isn't reachable, fix the model server first: on the
Mac, check `ipconfig getifaddr en0` against the LaunchAgent's `OLLAMA_HOST`.
Without the model server, every agent answer fails. **STOP** on
anything else. A not-ready Deployment must be fixed first so later failures
can be attributed. An existing object means an earlier attempt left something
behind. A NetworkPolicy on postgres or Aperture would block the new traffic.

### 3. Import both images (sudo)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
for pair in "order-diagnostics:$DIAG_IMG" "aperture-metrics:$APER_IMG"; do
  file=${pair%%:*}; img=${pair#*:}
  gzip -dc "$H/$file.tar.gz" | sudo k3s ctr -n k8s.io images import --platform linux/amd64 -
  got=$(sudo k3s crictl inspecti -o json "docker.io/library/$img" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"]["id"])')
  want=$(tr -d '[:space:]' < "$H/$file.image-id")
  echo "$img  k3s=$got  mac=$want"; test "$got" = "$want"
done
echo "STEP 3 OK: k3s has exactly the images built on the Mac"
STEP
```

**Success:** both ID pairs are equal and the block prints `STEP 3 OK`.
Importing adds images. No workload uses them yet.

### 4. Service and NetworkPolicy for order-diagnostics

The renderer needs every Service's address before it renders Deployments.

**4a. Render and review (no change):**

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/opencti"
python3 infra/mvp/render-wsl.py --phase phase1 --output-dir "$RUN/rendered-phase1"
pick "$RUN/rendered-phase1/phase1-infrastructure.yaml" \
  Service/order-diagnostics NetworkPolicy/order-diagnostics-boundary > "$RUN/diag-network.yaml"
cat "$RUN/diag-network.yaml"
STEP
```

**Review:**

- `podSelector` is exactly `app.kubernetes.io/name: order-diagnostics`.
- Ingress has one `from` item with both `namespaceSelector … lndops-agent` and
  `podSelector … paid-scan-diagnostics`, on port 8443.
- Egress is DNS (kube-system 53) and postgres 5432 only.

**4b. Create:**

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" create -f "$RUN/diag-network.yaml"
"${kn[@]}" get svc order-diagnostics -o jsonpath='{.spec.clusterIP}' > "$RUN/order-diagnostics.ip"
echo "Service IP: $(cat "$RUN/order-diagnostics.ip")"
STEP
```

`create` fails instead of overwriting if the object exists.

### 5. Render against copies of the old maps (no change)

The 2026-09-28 files are copied, never edited. There are three map changes:

- the new Service address;
- the new diagnostics image;
- the Aperture source image switches from `:latest` to `:metrics-20260929`.
  The committed manifests no longer reference `:latest`, and the renderer
  rejects unknown entries.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/opencti"
cp "$OLD_RUN/image-map.json" "$OLD_RUN/addresses.json" "$RUN/"
python3 - "$RUN" "$DIAG_IMG" "$APER_IMG" <<'PY'
import ipaddress, json, sys
from pathlib import Path
run, diag, aper = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
a = json.loads((run / "addresses.json").read_text())
ip = (run / "order-diagnostics.ip").read_text().strip()
assert ipaddress.ip_address(ip).version == 4 and "order-diagnostics" not in a["services"]
a["services"]["order-diagnostics"] = ip
(run / "addresses.json").write_text(json.dumps(a, indent=2) + "\n")
i = json.loads((run / "image-map.json").read_text())
assert diag not in i and aper not in i
i.pop("opencti-payments-fixture-aperture:latest", None)
i[diag] = diag   # local tags, as on 2026-09-28; contents verified in step 3
i[aper] = aper
(run / "image-map.json").write_text(json.dumps(i, indent=2) + "\n")
PY
diff "$OLD_RUN/addresses.json" "$RUN/addresses.json" || true
diff "$OLD_RUN/image-map.json" "$RUN/image-map.json" || true
python3 infra/mvp/render-wsl.py --phase all --output-dir "$RUN/rendered" \
  --image-map "$RUN/image-map.json" --address-map "$RUN/addresses.json" \
  --run-id "$(cat "$OLD_RUN/run-id")"
pick "$RUN/rendered/phase3-applications.yaml" Deployment/order-diagnostics > "$RUN/diag-deployment.yaml"
grep -nE 'image:|envFrom' "$RUN/diag-deployment.yaml"
STEP
```

**Success:**

- The address diff adds one entry. The image-map diff adds two entries and
  removes the `:latest` Aperture entry.
- The render succeeds.
- `diag-deployment.yaml` uses `$DIAG_IMG` and has no `envFrom`.

**STOP** on `service address map mismatch` or `unknown source images`: the
committed manifests differ from the 2026-09-28 checkout.

### 6. Credentials

**6a. List tenants (read-only).** This namespace is the E2E environment, and
every tenant in it was created by its provisioning Job.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" exec deploy/postgres -- psql -U scan_admin -d scan_control -Atc "select id, database_name, created_at from tenants order by created_at"
STEP
```

**6b. Generate and review.** The script writes two Secret manifests to `$P`
(mode 0700) and applies nothing.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
TENANTS=''   # tenant IDs from 6a, separated by spaces
test -n "$TENANTS"
args=(); for t in $TENANTS; do args+=(--tenant "$t"); done
"$WORK/lnd-ops/ops/provision-paid-scan-diagnostics" "${args[@]}"
python3 - "$P" <<'PY'  # names and keys only, never values
import json, sys
from pathlib import Path
for f in sorted(Path(sys.argv[1]).glob("*.json")):
    d = json.loads(f.read_text())
    print(f.name, d["metadata"]["namespace"], d["metadata"]["name"], sorted(d["data"]))
PY
STEP
```

**Success:** exactly these two lines. Never `cat` these files or paste them
anywhere.

```text
order-diagnostics-server.secret.json opencti-paid-scan-e2e order-diagnostics-server ['tenants.allowlist', 'tls.crt', 'tls.key', 'token.sha256']
paid-scan-diagnostics-client.secret.json lndops-agent paid-scan-diagnostics-client ['ca.crt', 'token']
```

**6c. Create:**

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${k[@]}" create -f "$P/order-diagnostics-server.secret.json" -f "$P/paid-scan-diagnostics-client.secret.json"
STEP
```

### 7. Start order-diagnostics

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" create -f "$RUN/diag-deployment.yaml"
"${kn[@]}" rollout status deploy/order-diagnostics --timeout=3m
"${kn[@]}" get deployments -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.generation}{"\n"}{end}' |
  grep -v '^order-diagnostics ' | diff "$RUN/deployments.before" -
echo "STEP 7 OK: order-diagnostics ready; existing Deployments unchanged"
STEP
```

If the rollout times out, check `describe pod` and `logs` for
`order-diagnostics`. A `KeyError` or TLS error means a Secret key or mount
mismatch.

**End of Part A.** Only new objects exist so far. The agent isn't deployed yet.

## Part B: Aperture metrics (changes existing objects)

Aperture restarts once. It keeps its SQLite database on its PVC, so issued
L402 tokens stay valid. The new image is upstream `311220b`, the same version
as now, plus the metrics, so there are no database migrations. Requests during
the restart fail briefly. This is the E2E environment.

### 8. Render and gate the Aperture changes (no change)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/opencti"
"${kn[@]}" create configmap l402-aperture-config \
  --from-file=aperture.yaml=infra/payments/aperture/aperture.yaml --dry-run=client -o yaml > "$RUN/aperture-config.yaml"
pick "$RUN/rendered-phase1/phase1-infrastructure.yaml" Service/l402-aperture > "$RUN/aperture-service.yaml"
pick "$RUN/rendered/phase3-applications.yaml" Deployment/l402-aperture > "$RUN/aperture-deployment.yaml"
for f in aperture-config aperture-service aperture-deployment; do
  echo "===== $f"; "${kn[@]}" diff -f "$RUN/$f.yaml" | tee "$RUN/evidence/$f.diff" || true
done
STEP
```

**Review.** Each diff may contain **only** these changes:

| Object | Allowed change |
|---|---|
| ConfigMap `l402-aperture-config` | Adds `prometheus: {enabled: true, listenaddr: "0.0.0.0:9000"}` and a comment above `authscheme` |
| Service `l402-aperture` | Adds port `metrics` 9000 |
| Deployment `l402-aperture` | Image becomes `opencti-payments-fixture-aperture:metrics-20260929`; adds container port `metrics` 9000; the `generation` and `last-applied` metadata change |

**STOP** if any other line changes, for example resources, env, volumes,
`nodeSelector` or the image of `payment-aperture-services`. The committed
manifests have drifted from what's running, and that needs review.

### 9. Apply (restarts Aperture)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" apply -f "$RUN/aperture-config.yaml" -f "$RUN/aperture-service.yaml" -f "$RUN/aperture-deployment.yaml"
"${kn[@]}" rollout status deploy/l402-aperture --timeout=3m
"${kn[@]}" get deployments -o jsonpath='{range .items[*]}{.metadata.name} {.metadata.generation}{"\n"}{end}' |
  grep -vE '^(order-diagnostics|l402-aperture) ' | diff <(grep -v '^l402-aperture ' "$RUN/deployments.before") -
echo "STEP 9 OK: Aperture restarted; other Deployments unchanged"
STEP
```

The ConfigMap changes before the Deployment, so the new pod starts with
Prometheus enabled.

### 10. Verify the metrics endpoint

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kn[@]}" port-forward svc/l402-aperture 19000:9000 >/dev/null 2>&1 &
trap 'kill $! 2>/dev/null' EXIT
for i in $(seq 30); do curl -s -o /dev/null http://127.0.0.1:19000/metrics && break; sleep 1; done
curl -s http://127.0.0.1:19000/metrics | grep '^aperture_l402_' | tee "$RUN/evidence/aperture-metrics.txt"
test "$(grep -c '^aperture_l402_' "$RUN/evidence/aperture-metrics.txt")" -eq 17
grep -q 'reason="missing_credentials"' "$RUN/evidence/aperture-metrics.txt"
echo "STEP 10 OK: 17 L402 series exposed"
STEP
```

**Success:** 17 lines: 6 mint results and 11 verify reasons. They're at 0,
or higher if traffic already arrived.

**Rollback for Part B:** re-apply the three objects from the 2026-09-28
render (`$OLD_RUN/rendered/…`), which keeps the `:latest` image and the old
config.

## Part C: monitoring (changes existing objects)

### 11. Gate the Prometheus changes (no change)

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/lnd-ops"
(cd charts/vendor && sha256sum --check --ignore-missing SHA256SUMS | grep kube-prometheus-stack)
helm --kube-context "$CTX" -n lndops-monitoring get values lnd-ops-monitoring -o yaml > "$RUN/monitoring-live-values.yaml"
python3 - "$RUN/monitoring-live-values.yaml" charts/monitoring-values.yaml <<'PY'
import sys, yaml
live, new = (yaml.safe_load(open(p)) or {} for p in sys.argv[1:3])
def jobs(v):
    return v["prometheus"]["prometheusSpec"].get("additionalScrapeConfigs", [])
added = [j["job_name"] for j in jobs(new) if j not in jobs(live)]
removed = [j["job_name"] for j in jobs(live) if j not in jobs(new)]
strip = lambda v: {**v, "prometheus": {**v["prometheus"], "prometheusSpec": {k: x for k, x in v["prometheus"]["prometheusSpec"].items() if k != "additionalScrapeConfigs"}}}
same_rest = strip(live) == strip(new)
print("added jobs:", added, "| removed jobs:", removed, "| other values identical:", same_rest)
assert added == ["aperture"] and not removed and same_rest, "monitoring values differ beyond the aperture job"
PY
"${k[@]}" diff -f charts/monitoring-rules.yaml | tee "$RUN/evidence/monitoring-rules.diff" || true
echo "STEP 11 GATE OK (review the rules diff)"
STEP
```

**Success:** `added jobs: ['aperture'] | removed jobs: [] | other values
identical: True`. The rules diff adds only the `opencti-l402` group (4 alerts).
**STOP** otherwise. The live monitoring release differs from this branch, and
an upgrade would change more than intended.

### 12. Apply and verify

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/lnd-ops"
helm --kube-context "$CTX" upgrade lnd-ops-monitoring charts/vendor/kube-prometheus-stack-91.4.1.tgz \
  --namespace lndops-monitoring --values charts/monitoring-values.yaml --wait --timeout 15m
"${k[@]}" apply -f charts/monitoring-rules.yaml
"${km[@]}" port-forward svc/lnd-ops-monitoring-kube-pr-prometheus 19090:9090 >/dev/null 2>&1 &
trap 'kill $! 2>/dev/null' EXIT
for i in $(seq 90); do
  up=$(curl -s --get http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=max(up{job="aperture"})' |
       python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")')
  [ "$up" = "1" ] && break; sleep 2
done
test "$up" = "1"
curl -s http://127.0.0.1:19090/api/v1/rules | python3 -c '
import json, sys
g = [g for g in json.load(sys.stdin)["data"]["groups"] if g["name"] == "opencti-l402"]
print("opencti-l402 rules:", [r["name"] for r in g[0]["rules"]] if g else "missing"); assert g and len(g[0]["rules"]) == 4'
echo "STEP 12 OK: Aperture scraped (up=1) and 4 L402 alerts loaded"
STEP
```

It can take up to about a minute for Prometheus to reload its config and
scrape the new target.

## Part D: the agent

### 13. Change gate (read-only)

`ops/deploy-agent` reapplies the whole agent chart, rewrites ConfigMaps from
files and restarts `runbook-gateway`. This gate proves the only differences
are paid-scan additions, so live work that isn't on this branch, such as
uncommitted Router changes, can't be silently reverted.

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
# Every committed revision the LND side may legitimately be at: pre-Router, Router, and each later
# commit on this branch that changed the LND agent chart or gateway. Extracted without a worktree.
KN="$RUN/known"; rm -rf "$KN"
for r in '6603fb3~1' 6603fb3 $(git log --format=%H 6603fb3..HEAD -- charts/agent/templates/kagent.yaml charts/agent/templates/resources.yaml agent/runbook_gateway.py); do
  sha=$(git rev-parse "$r"); d="$KN/$sha"; mkdir -p "$d/src" "$d/runbooks"
  git archive "$sha" charts/agent | tar -x -C "$d/src"
  helm template lnd-ops-agent "$d/src/charts/agent" -n lndops-agent -f "$RUN/agent-live-values.yaml" \
    --set paidScan.enabled=false > "$d/render.yaml"
  git show "$sha:agent/runbook_gateway.py" > "$d/gateway.py"
  for f in $(git show "$sha:ops/deploy-agent" | grep -o 'docs/runbooks/[A-Za-z0-9._-]*\.md' | sort -u); do
    git show "$sha:$f" > "$d/runbooks/$(basename "$f")"   # the runbooks deploy-agent shipped at that revision
  done
done
python3 - "$RUN" <<'PY'
import json, sys, yaml
from pathlib import Path
run = Path(sys.argv[1])
def objs(text):
    return {(d["kind"], d["metadata"].get("namespace", "lndops-agent"), d["metadata"]["name"]): d
            for d in yaml.safe_load_all(text) if d}
paid = lambda k: "paid-scan" in k[2]
live, new = objs((run / "agent-live.yaml").read_text()), objs((run / "agent-new.yaml").read_text())
removed = sorted(k for k in live if k not in new)
added = sorted(set(new) - set(live))
lnd = {k: v for k, v in live.items() if not paid(k)}
print("added:", added); print("removed:", removed)
if removed: sys.exit(f"STOP: the chart would remove live objects: {removed}")
if [k for k in added if not paid(k)]: sys.exit(f"STOP: non-paid-scan objects would be added: {[k for k in added if not paid(k)]}")
if not added: sys.exit("STOP: no paid-scan objects would be added")
src = json.loads((run / "cm-source.json").read_text())["data"]["runbook_gateway.py"]
books = json.loads((run / "cm-runbooks.json").read_text())["data"]
matched, explained = [], set()
for d in sorted((run / "known").iterdir()):
    ref = {k: v for k, v in objs((d / "render.yaml").read_text()).items() if not paid(k)}
    same = {k for k in lnd if ref.get(k) == lnd[k]}
    explained |= same
    files = src == (d / "gateway.py").read_text() and books == {p.name: p.read_text() for p in (d / "runbooks").glob("*.md")}
    if same == set(lnd) == set(ref) and files:
        matched.append(d.name)
if not matched:
    sys.exit(f"STOP: live LND objects match no known committed revision: {sorted(set(lnd) - explained)}"
             " (or the gateway code or runbooks differ from every revision's)")
print(f"live LND side matches committed revision {matched[0]}")
print(f"GATE OK: {len(added)} paid-scan objects added; LND objects and gateway code move from that revision to this branch")
PY
STEP
```

**Success:** `GATE OK` after `live LND side matches committed revision <sha>`.

- `removed` is empty, and every added object is a paid-scan one: the tool pod
  and its RBAC, the eval fixture, both Agents and both RemoteMCPServers.
- Every non-paid-scan live object, the live `runbook_gateway.py` and the live
  runbooks ConfigMap must all equal one known committed revision (pre-Router
  `6603fb3~1`, the Router commit `6603fb3`, or a later commit on this branch
  that changed the LND agent or gateway). Changed LND objects are then fine:
  they move from that revision to this branch.

**STOP** on anything else, with the list of objects that match no known
revision. Live objects are then in a state this branch
doesn't know about.

### 14. Deploy

`deploy-agent` ships only committed playbooks and records their git revision.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/lnd-ops"
ops/deploy-agent --agent-values charts/agent/paid-scan-wsl-e2e.values.yaml
"${ka[@]}" rollout status deploy/paid-scan-diagnostics --timeout=3m
"${ka[@]}" rollout status deploy/paid-scan-eval-fixture --timeout=3m
"${kk[@]}" get agent/paid-scan-diagnosis agent/paid-scan-diagnosis-eval remotemcpserver/paid-scan-diagnostics remotemcpserver/paid-scan-eval
test "$("${ka[@]}" get configmap paid-scan-playbooks -o jsonpath='{.data.revision}')" = "$(git rev-parse HEAD)"
echo "STEP 14 OK"
STEP
```

**Success:**

- `OK Phase 7 agent deployed: kagent=0.9.12 provider=Ollama model=…`;
- both rollouts complete and the four kagent objects are listed;
- the playbook revision equals this checkout's HEAD;
- `STEP 14 OK`.

## Part E: acceptance

### 15. Direct tool calls (no LLM)

First find a finished order: pick a `database_name` from 6a and look for a row
whose third column (scan state) is `completed`.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
DB=''   # a database_name from 6a
test -n "$DB"
"${kn[@]}" exec deploy/postgres -- psql -U scan_admin -d "$DB" -Atc \
  "select o.id, o.state, s.state from orders o left join scans s on s.order_id = o.id order by o.created_at desc limit 5"
STEP
```

Then call every tool:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
T=''; O=''   # tenant id, and an order id whose scan state is completed
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
echo "== completed order"; tool diagnose_paid_order "{\"tenant_id\":\"$T\",\"order_id\":\"$O\"}" | tee "$RUN/evidence/15-order.json"
echo "== unknown order";   tool diagnose_paid_order "{\"tenant_id\":\"$T\",\"order_id\":\"00000000-0000-4000-8000-000000000000\"}" | tee "$RUN/evidence/15-unknown.json"
echo "== workload";        tool get_opencti_workload_status '{}' | tee "$RUN/evidence/15-workload.json"
echo "== funnel";          tool diagnose_l402_funnel '{}' | tee "$RUN/evidence/15-funnel.json"
echo "== playbook";        tool get_playbook '{"name":"opencti-l402-funnel"}' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["name"], d["revision"], d["sha256"], len(d["content"]))'
echo "== endpoint down"
trap '"${kn[@]}" scale deploy/order-diagnostics --replicas=1 >/dev/null; "${kn[@]}" rollout status deploy/order-diagnostics --timeout=3m' EXIT
"${kn[@]}" scale deploy/order-diagnostics --replicas=0
"${kn[@]}" wait --for=delete pod -l app.kubernetes.io/name=order-diagnostics --timeout=2m || true
tool diagnose_paid_order "{\"tenant_id\":\"$T\",\"order_id\":\"$O\"}" | tee "$RUN/evidence/15-down.json"
STEP
```

| Call | Expected |
|---|---|
| Completed order | `order_state: paid`, `scan_state: completed`, `result_recorded: true`, and `observed_at` within 30 seconds |
| Unknown order | `status: unknown`, `not_found_or_not_visible` |
| Workload | `status: observed`, 14 Deployments including `order-diagnostics`, and no `message` field |
| Funnel | `status: observed`, `scope: l402`. The verdict is probably `no_l402_traffic`: nothing paid through L402 since Aperture restarted |
| Playbook | Name, a 40-character revision equal to step 14's HEAD, a sha256, and non-zero length |
| Endpoint down | `status: unknown`, never a stage. The block scales back automatically, even on failure |

### 16. Agent evaluation

This runs the five fixture scenarios (tabletops 1–3, a healthy baseline and
an unavailable diagnosis) three times each against the `paid-scan-diagnosis-eval`
agent. That agent shares its model, system message and tools with production.

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
cd "$WORK/lnd-ops"
ops/eval-paid-scan-agent --runs 3 --out "$RUN/evidence/eval" | tee "$RUN/evidence/eval-summary.txt"
STEP
```

**Reading the result:**

- The script prints a pass rate per scenario and fails if any scenario is
  below 2/3.
- **A failure here is a finding, not a broken rollout.** The deployment is
  complete after step 15.
- For each failed run, the evidence JSON shows which check failed:
  - a missing `get_playbook` call;
  - a required point not mentioned;
  - a forbidden recommendation.
- Decide per finding whether the playbook, the system message or the
  grader's heuristic is wrong. The grader was only checked against canned
  answers before this first live run.

Then ask the production agent one real question and compare it with 15's
evidence:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
"${kk[@]}" port-forward service/kagent-controller 18083:8083 >/dev/null 2>&1 &
trap 'kill $! 2>/dev/null' EXIT
for i in $(seq 30); do curl -s -o /dev/null http://127.0.0.1:18083/ && break; sleep 1; done
"$WORK/lnd-ops/ops/kagent-cli" --kagent-url http://127.0.0.1:18083 --namespace lndops-kagent \
  invoke --agent paid-scan-diagnosis --timeout 8m \
  --task "Is the L402 payment gate healthy right now? Use the playbook." | tee "$RUN/evidence/16-agent.txt"
STEP
```

**Success:**

- It calls `get_playbook` and `diagnose_l402_funnel`.
- Its verdict matches `15-funnel.json`.
- It names the playbook section it used.
- It claims no fault that the tool output doesn't show.

## Rollback

Undo in reverse order, and only as far as needed:

```bash
bash -euo pipefail <<'STEP'
source ~/paid-scan-diag.env
# D: agent (paidScan disabled → paid-scan and eval objects removed)
(cd "$WORK/lnd-ops" && ops/deploy-agent)
"${ka[@]}" delete secret paid-scan-diagnostics-client --ignore-not-found
# C: monitoring. Reinstall the previous values (saved in step 11) and delete the added rule group by re-applying the old rules file from the old checkout
# B: Aperture. Re-apply the 2026-09-28 rendered objects for l402-aperture (image :latest, old config)
# A: order-diagnostics
"${kn[@]}" delete deploy/order-diagnostics svc/order-diagnostics networkpolicy/order-diagnostics-boundary secret/order-diagnostics-server --ignore-not-found
STEP
```

- **For Part D,** run the step 13 gate again first; it must pass for the same
  reason as before.
- **For Part C,** run `helm upgrade` with `-f "$RUN/monitoring-live-values.yaml"`
  and re-apply the old rules file.
- **For Part B,** `$OLD_RUN` holds the old rendered manifests.
- **Leftovers:** the imported images are inert; remove them with
  `sudo k3s ctr -n k8s.io images rm docker.io/library/<image>`. Delete `$P`
  once the credentials are no longer needed.
