"""Runs the step 13 change-gate Python from docs/paid-scan-wsl-rollout.md against renders of real committed revisions."""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = pathlib.Path(__file__).parents[1]
PATHS = ["charts/agent/templates/kagent.yaml", "charts/agent/templates/resources.yaml", "agent/runbook_gateway.py"]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def gate_python():
    doc = (ROOT / "docs/paid-scan-wsl-rollout.md").read_text()
    step = doc.split("### 13. Change gate", 1)[1].split("### 14.", 1)[0]
    return re.search(r"<<'PY'\n(.*?)\nPY\n", step, re.S).group(1)


def render(chart, *sets):
    cmd = ["helm", "template", "lnd-ops-agent", str(chart), "-n", "lndops-agent"]
    for s in sets:
        cmd += ["--set", s]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def skip_reason():
    if not shutil.which("helm"):
        return "helm not installed"
    if yaml is None:
        return "PyYAML not installed"
    try:
        git("rev-parse", "6603fb3", "6603fb3~1")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "git history with 6603fb3 not available"
    return ""


@unittest.skipIf(skip_reason(), skip_reason())
class RolloutGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = pathlib.Path(cls.tmp.name)
        cls.shas = [git("rev-parse", r).strip() for r in ("6603fb3~1", "6603fb3")]
        cls.shas += git("log", "--format=%H", "6603fb3..HEAD", "--", *PATHS).split()
        cls.known = cls.base / "known"
        for sha in cls.shas:
            d = cls.known / sha
            (d / "runbooks").mkdir(parents=True)
            subprocess.run(f"git archive {sha} charts/agent | tar -x -C {d}", shell=True, cwd=ROOT, check=True)
            (d / "render.yaml").write_text(render(d / "charts/agent", "paidScan.enabled=false"))
            (d / "gateway.py").write_text(git("show", f"{sha}:agent/runbook_gateway.py"))
            for f in sorted(set(re.findall(r"docs/runbooks/[\w.-]+\.md", git("show", f"{sha}:ops/deploy-agent")))):
                (d / "runbooks" / pathlib.Path(f).name).write_text(git("show", f"{sha}:{f}"))
        cls.new = render(ROOT / "charts/agent", "paidScan.enabled=true", "paidScan.origin=https://d.example:8443")
        cls.gate = cls.base / "gate.py"
        cls.gate.write_text(gate_python())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_gate(self, sha, tamper=False, gateway=None):
        d = self.known / sha
        live = d.joinpath("render.yaml").read_text()
        if tamper:
            docs = [x for x in yaml.safe_load_all(live) if x]
            gw = next(x for x in docs if x["kind"] == "Deployment" and x["metadata"]["name"] == "runbook-gateway")
            gw["spec"]["template"]["spec"]["containers"][0]["resources"] = {"limits": {"cpu": "9999m"}}
            live = yaml.safe_dump_all(docs)
        run = self.base / "run"
        shutil.rmtree(run, ignore_errors=True)
        run.mkdir()
        (run / "agent-live.yaml").write_text(live)
        (run / "agent-new.yaml").write_text(self.new)
        gateway = d.joinpath("gateway.py").read_text() if gateway is None else gateway
        books = {p.name: p.read_text() for p in (d / "runbooks").glob("*.md")}
        (run / "cm-source.json").write_text(json.dumps({"data": {"runbook_gateway.py": gateway}}))
        (run / "cm-runbooks.json").write_text(json.dumps({"data": books}))
        (run / "known").symlink_to(self.known)
        return subprocess.run(["python3", str(self.gate), str(run)], capture_output=True, text=True)

    def test_router_commit_is_known(self):
        r = self.run_gate(self.shas[1])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"live LND side matches committed revision {self.shas[1]}", r.stdout)
        self.assertIn("GATE OK", r.stdout)

    def test_pre_router_is_known(self):
        r = self.run_gate(self.shas[0])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"committed revision {self.shas[0]}", r.stdout)

    def test_tampered_limit_stops(self):
        r = self.run_gate(self.shas[0], tamper=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("STOP", r.stderr)
        self.assertIn("runbook-gateway", r.stderr)

    def test_unknown_gateway_stops(self):
        r = self.run_gate(self.shas[1], gateway="# uncommitted live edit\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("STOP", r.stderr)


if __name__ == "__main__":
    unittest.main()
