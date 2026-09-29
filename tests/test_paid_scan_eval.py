import importlib.util
import importlib.machinery
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).parents[1]
SCENARIOS = ROOT / "tests/eval/scenarios"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture = load("paid_scan_eval_fixture", ROOT / "agent/paid_scan_eval_fixture.py")
prod = fixture.prod
TENANT = "11111111-1111-4111-8111-111111111111"
ORDER = "22222222-2222-4222-8222-222222222222"
ORDER_ARGS = {"tenant_id": TENANT, "order_id": ORDER}


class FixtureServerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = pathlib.Path(tmp.name, "state")
        self.scen = pathlib.Path(tmp.name, "scen")
        self.plays = pathlib.Path(tmp.name, "plays")
        for d in (self.state, self.scen, self.plays):
            d.mkdir()
        (self.plays / "opencti-l402-funnel.md").write_text("# funnel playbook\n")
        for name, verdict in (("one", "incident"), ("two", "healthy")):
            (self.scen / f"{name}.json").write_text(json.dumps(
                {"question": "q", "tools": {"diagnose_l402_funnel": {"status": "observed", "verdict": verdict}}, "expect": {}}))
        patch = unittest.mock.patch.dict("os.environ", {"STATE_DIR": str(self.state), "SCENARIO_DIR": str(self.scen),
                                                        "PLAYBOOK_DIR": str(self.plays)})
        patch.start()
        self.addCleanup(patch.stop)
        server = ThreadingHTTPServer(("127.0.0.1", 0), fixture.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def rpc(self, method, params=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/mcp", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        return json.load(urllib.request.urlopen(request, timeout=5))

    def tool(self, name, arguments=None):
        reply = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return json.loads(reply["result"]["content"][0]["text"])

    def activate(self, text):
        (self.state / "active").write_text(text)

    def test_tool_schemas_are_the_production_dicts(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual(tools, [prod.TOOL, prod.WORKLOAD_TOOL, prod.FUNNEL_TOOL, prod.PLAYBOOK_TOOL])

    def test_active_scenario_is_read_per_call(self):
        self.activate("one")
        self.assertEqual(self.tool("diagnose_l402_funnel")["verdict"], "incident")
        self.activate("two")
        self.assertEqual(self.tool("diagnose_l402_funnel")["verdict"], "healthy")

    def test_missing_unknown_invalid_or_absent_tool_is_not_configured(self):
        expected = {"status": "unknown", "reason": "not_configured"}
        self.assertEqual(self.tool("diagnose_l402_funnel"), expected)  # no active file
        for active in ("nope", "../one", "ONE", "one\n../x", "a" * 65):
            self.activate(active)
            self.assertEqual(self.tool("diagnose_l402_funnel"), expected, active)
        self.activate("one")
        self.assertEqual(self.tool("get_opencti_workload_status"), expected)

    def test_get_playbook_delegates_to_real_tool(self):
        self.activate("one")
        result = self.tool("get_playbook", {"name": "opencti-l402-funnel"})
        self.assertEqual(result, prod.get_playbook({"name": "opencti-l402-funnel"}))
        self.assertEqual(result["content"], "# funnel playbook\n")
        self.assertIn("error", self.rpc("tools/call", {"name": "get_playbook", "arguments": {"name": "../x"}}))

    def test_order_arguments_validated_but_ignored(self):
        self.activate("two")
        (self.scen / "two.json").write_text(json.dumps({"tools": {"diagnose_paid_order": {"stage": "canned"}}}))
        self.assertEqual(self.tool("diagnose_paid_order", ORDER_ARGS), {"stage": "canned"})
        for bad in ({}, {"tenant_id": TENANT}, {**ORDER_ARGS, "x": 1}, {"tenant_id": "x", "order_id": ORDER}):
            self.assertIn("error", self.rpc("tools/call", {"name": "diagnose_paid_order", "arguments": bad}))
        self.assertIn("error", self.rpc("tools/call", {"name": "diagnose_l402_funnel", "arguments": {"a": 1}}))
        self.assertIn("error", self.rpc("tools/call", {"name": "other", "arguments": {}}))

    def test_healthz(self):
        reply = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz", timeout=5))
        self.assertEqual(reply["status"], "ready")


class ScenarioFileTests(unittest.TestCase):
    def test_scenarios_are_valid(self):
        files = sorted(SCENARIOS.glob("*.json"))
        self.assertEqual(len(files), 5)
        known = {t["name"] for t in fixture.TOOLS}
        for path in files:
            self.assertRegex(path.stem, r"[a-z0-9-]{1,64}")
            data = json.loads(path.read_text())
            self.assertEqual(set(data), {"question", "tools", "expect"}, path.name)
            self.assertTrue(data["question"].strip())
            self.assertTrue(set(data["tools"]) <= known - {"get_playbook"}, path.name)
            expect = data["expect"]
            self.assertLessEqual({"required_tools", "must_mention", "must_not"}, set(expect), path.name)
            self.assertTrue(set(expect["required_tools"]) <= known, path.name)
            if "playbook" in expect:
                self.assertIn(expect["playbook"], prod.PLAYBOOKS)
                self.assertTrue((ROOT / f"docs/playbooks/{expect['playbook']}.md").is_file())
                self.assertIn("get_playbook", expect["required_tools"])
            for group in expect["must_mention"]:
                self.assertTrue(group and all(isinstance(g, str) for g in group))
            for rx in expect["must_not"]:
                re.compile(rx)
            for tool in expect["required_tools"]:  # a required tool must be answerable
                self.assertTrue(tool == "get_playbook" or tool in data["tools"], (path.name, tool))


def helm(*sets):
    cmd = ["helm", "template", "r", str(ROOT / "charts/agent"), "--namespace", "lndops-agent",
           "--set", "paidScan.enabled=true", "--set", "paidScan.origin=https://diagnostics.example:8443"]
    for s in sets:
        cmd += ["--set", s]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def docs(rendered):
    out = {}
    for doc in re.split(r"^---\n", rendered, flags=re.M):
        kind = re.search(r"^kind: (\S+)", doc, re.M)
        name = re.search(r"^  name: (\S+)", doc, re.M) or re.search(r"^metadata: \{name: ([^,}]+)", doc, re.M)
        if kind and name:
            out[(kind.group(1), name.group(1))] = doc
    return out


def system_message(doc):
    return re.search(r"systemMessage: \|\n(.*?)\n    tools:", doc, re.S).group(1)


@unittest.skipUnless(shutil.which("helm"), "helm not installed")
class ChartTests(unittest.TestCase):
    def test_eval_is_off_by_default(self):
        rendered = helm()
        self.assertNotIn("paid-scan-eval", rendered)
        self.assertIn(("Agent", "paid-scan-diagnosis"), docs(rendered))

    def test_eval_objects_render_when_enabled(self):
        found = docs(helm("paidScan.eval.enabled=true"))
        for key in (("Deployment", "paid-scan-eval-fixture"), ("Service", "paid-scan-eval-fixture"),
                    ("NetworkPolicy", "paid-scan-eval-fixture"), ("NetworkPolicy", "kagent-paid-scan-eval"),
                    ("RemoteMCPServer", "paid-scan-eval"), ("Agent", "paid-scan-diagnosis-eval")):
            self.assertIn(key, found)
        deployment = found[("Deployment", "paid-scan-eval-fixture")]
        self.assertIn("automountServiceAccountToken: false", deployment)
        self.assertNotIn("secret", deployment.lower())
        self.assertIn("paid_scan_eval_fixture.py", deployment)
        for volume in ("runbook-gateway-source", "paid-scan-playbooks", "paid-scan-eval-scenarios", "emptyDir"):
            self.assertIn(volume, deployment)
        policy = found[("NetworkPolicy", "paid-scan-eval-fixture")]
        self.assertIn("lndops-kagent", policy)
        self.assertNotIn("ipBlock", policy)
        self.assertNotIn("lndops-monitoring", policy)

    def test_both_agents_share_message_and_tools(self):
        found = docs(helm("paidScan.eval.enabled=true"))
        prod, ev = found[("Agent", "paid-scan-diagnosis")], found[("Agent", "paid-scan-diagnosis-eval")]
        self.assertEqual(system_message(prod), system_message(ev))
        self.assertIn("call get_playbook", system_message(ev))
        tools = lambda doc: re.search(r"toolNames: (\[.*?\])", doc).group(1)
        self.assertEqual(tools(prod), tools(ev))
        self.assertIn("name: paid-scan-eval\n", ev)
        self.assertIn("modelConfig: default-model-config", ev)


if __name__ == "__main__":
    unittest.main()
