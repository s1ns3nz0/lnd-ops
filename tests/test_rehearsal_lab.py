import importlib.machinery
import importlib.util
import json
import pathlib
import re
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


exporter = load("aperture_exporter", "lab/rehearsal/aperture_exporter.py")
lab = load("rehearsal_lab", "ops/rehearsal-lab")
diag = load("paid_scan_diagnostics", "agent/paid_scan_diagnostics.py")
RULES = (ROOT / "charts/monitoring-rules.yaml").read_text()
SAMPLE = re.compile(r'^([a-z0-9_]+)\{([a-z]+)="([a-z_]+)"\} (\d+)$')


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def samples(text):
    return {(m[1], m[3]): int(m[4]) for m in map(SAMPLE.match, text.splitlines()) if m}


class ExporterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name) / "rates.json"
        self.clock = Clock()
        self.exp = exporter.Exporter(str(self.path), self.clock)

    def scrape(self, advance=0):
        self.clock.now += advance
        return samples(self.exp.render())

    def test_exactly_the_17_series_all_zero_without_rates_file(self):
        first = self.scrape()
        self.assertEqual(len(first), 17)
        self.assertEqual({k[0] for k in first}, {"aperture_l402_mint_total", "aperture_l402_verify_total"})
        self.assertEqual(set(first.values()), {0})
        self.assertEqual(self.scrape(600), first)  # missing file: still zeros after time passes

    def test_valid_prometheus_text(self):
        self.path.write_text(json.dumps({"mint": {"ok": 2}}))
        lines = self.exp.render().splitlines()
        self.assertEqual(len(lines), 17 + 4)
        for line in lines:
            self.assertRegex(line, r'^(# HELP \w+ .+|# TYPE \w+ counter|\w+\{\w+="\w+"\} \d+)$')

    def test_counters_grow_at_rate_and_never_decrease(self):
        self.path.write_text(json.dumps({"mint": {"ok": 2}, "verify": {"accepted": 6}}))
        a = self.scrape(60)
        self.assertEqual((a[("aperture_l402_mint_total", "ok")], a[("aperture_l402_verify_total", "accepted")]), (2, 6))
        self.path.write_text(json.dumps({"mint": {"ok": 0}}))
        b = self.scrape(60)
        self.assertEqual(b[("aperture_l402_mint_total", "ok")], 2)
        self.path.unlink()
        c = self.scrape(60)
        self.path.write_text("not json")
        d = self.scrape(60)
        self.path.write_text(json.dumps({"mint": {"ok": 1}, "verify": {"accepted": -5}}))
        e = self.scrape(60)
        for key in a:
            self.assertTrue(a[key] <= b[key] <= c[key] <= d[key] <= e[key], key)

    def test_bad_values_are_zero(self):
        self.path.write_text(json.dumps({"mint": {"ok": "x", "challenge_failed": True, "bogus": 5}, "verify": []}))
        self.assertEqual(set(self.scrape(60).values()), {0})

    def test_fractional_carry(self):
        self.path.write_text(json.dumps({"mint": {"ok": 1}}))
        for _ in range(7):
            last = self.scrape(10)
        self.assertEqual(last[("aperture_l402_mint_total", "ok")], 1)

    def test_series_match_funnel_queries_and_rules(self):
        mint, verify = set(exporter.MINT), set(exporter.VERIFY)
        self.assertEqual(mint - {"ok"}, set(diag.MINT_RESULTS))
        self.assertTrue(set(diag.REJECT_REASONS) <= verify)
        text = "\n".join(diag.FUNNEL_QUERIES.values()) + RULES
        for label, values in (("result", mint), ("reason", verify)):
            for match in re.finditer(rf'{label}(=~?)"([\w|]+)"', text):
                self.assertTrue(set(match.group(2).split("|")) <= values, match.group(0))
        self.assertIn("aperture_l402_mint_total", text)
        self.assertIn("aperture_l402_verify_total", text)
        values = (ROOT / "charts/monitoring-values.yaml").read_text()
        self.assertIn("job_name: aperture", values)
        self.assertIn("regex: metrics", values)


class ScenarioTest(unittest.TestCase):
    def test_names(self):
        self.assertEqual(set(lab.SCENARIOS), {"healthy", "pricer-down", "invoice-failure", "rejection-spike", "metrics-absent"})

    def test_only_dummy_workloads_are_broken(self):
        for name, s in lab.SCENARIOS.items():
            self.assertTrue(set(s["broken"]) <= set(lab.DUMMIES), name)
            self.assertNotIn(lab.APERTURE, s["broken"])
        self.assertEqual(lab.DUMMIES, ("payment-aperture-services", "lnd-merchant", "paid-scan-api", "paid-scan-internal",
                                       "paid-scan-dispatcher", "scanner-broker", "postgres"))

    def test_expected_alerts_and_playbook_sections_exist(self):
        playbook = (ROOT / lab.PLAYBOOK).read_text().splitlines()
        for name, s in lab.SCENARIOS.items():
            if s["alert"]:
                self.assertIn(f"- alert: {s['alert']}\n", RULES, name)
            self.assertIn(s["section"], playbook, name)

    def test_rates_use_known_series(self):
        for name, s in lab.SCENARIOS.items():
            for family, values in (s["rates"] or {}).items():
                known = {"mint": exporter.MINT, "verify": exporter.VERIFY}[family]
                self.assertTrue(set(values) <= set(known), name)
        self.assertEqual(lab.SCENARIOS["metrics-absent"]["replicas"], 0)
        self.assertEqual(lab.SCENARIOS["healthy"]["rates"], {
            "mint": {"ok": 2}, "verify": {"missing_credentials": 2, "accepted": 1, "credential_verified": 1,
                                          "invoice_state_mismatch": 1}})
        spike = lab.SCENARIOS["rejection-spike"]["rates"]["verify"]
        self.assertEqual((spike["invalid_signature"], spike["unknown_credential"]), (15, 12))
        self.assertEqual(lab.SCENARIOS["pricer-down"]["rates"], {"verify": {"missing_credentials": 2}})

    def test_workload_objects(self):
        objects = lab.workload_objects()
        names = [o["metadata"]["name"] for o in objects if o["kind"] == "Deployment"]
        self.assertEqual(set(names), {*lab.DUMMIES, lab.APERTURE})
        service = next(o for o in objects if o["kind"] == "Service")
        self.assertEqual(service["spec"]["ports"][0]["name"], "metrics")
        self.assertEqual(service["spec"]["ports"][0]["port"], 9000)

    def test_parse_host_address(self):
        self.assertEqual(lab.parse_host_address("192.168.65.254 STREAM host.docker.internal\n"), "192.168.65.254")
        with self.assertRaises(lab.LabError):
            lab.parse_host_address("::1 STREAM host.docker.internal\n")

    def test_shipped_runbooks_and_checksums(self):
        self.assertTrue(all(p.is_file() for p in lab.shipped_runbooks()))
        self.assertEqual(len(lab.expected_checksums()), 3)

    def test_parse_invocation(self):
        inv = {"history": [
            {"parts": [{"data": {"name": "diagnose_l402_funnel", "args": {}}}]},
            {"parts": [{"data": {"name": "diagnose_l402_funnel", "response": {"content": []}}}]},
            {"parts": [{"text": "all healthy"}]}]}
        self.assertEqual(lab.parse_invocation(inv), ("all healthy", [("diagnose_l402_funnel", {})]))


class GuardTest(unittest.TestCase):
    def test_refuses_other_context(self):
        with self.assertRaises(lab.LabError):
            lab.check_context("kind-other")
        lab.check_context("kind-lndops-rehearsal")

    def test_guarded_commands_refuse_before_acting(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = pathlib.Path(tmp) / "kubeconfig"
            config.write_text("x")
            for argv in (["inject", "healthy"], ["reset"], ["ui"], ["ask", "paid-scan-diagnosis", "q"]):
                with mock.patch.object(lab, "KUBECONFIG", config), \
                        mock.patch.object(lab, "current_context", return_value="minikube"), \
                        mock.patch.object(lab, "run") as run, mock.patch("sys.stderr"):
                    self.assertEqual(lab.main(argv), 1, argv)
                    run.assert_not_called()

    def test_missing_kubeconfig_refuses(self):
        with mock.patch.object(lab, "KUBECONFIG", pathlib.Path("/nonexistent/kubeconfig")), mock.patch("sys.stderr"):
            self.assertEqual(lab.main(["reset"]), 1)

    def test_script_never_touches_real_state_or_kubeconfig(self):
        text = (ROOT / "ops/rehearsal-lab").read_text()
        self.assertNotRegex(text, r"\.kube\b")
        self.assertNotRegex(text, r"state/lnd-ops(?!-rehearsal)")
        self.assertNotRegex(text, r'"lnd-ops"')
        self.assertEqual(lab.STATE.name, "lnd-ops-rehearsal")
        self.assertEqual(lab.KUBECONFIG.parent, lab.STATE)

    def test_every_kubectl_helm_kind_call_passes_the_kubeconfig(self):
        text = (ROOT / "ops/rehearsal-lab").read_text()
        for call in re.findall(r'\[\s*"(?:kubectl|helm)"[^\]]*\]', text):
            self.assertIn("KUBECONFIG", call)
        for call in re.findall(r'\["kind", "(?:create|export|delete)"[^\]]*\]', text):
            self.assertIn("KUBECONFIG", call)
        self.assertNotIn("subprocess.run(", text.replace("subprocess.run([str(a)", ""))


class ArgumentTest(unittest.TestCase):
    def bad(self, argv):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
            lab.parse_args(argv)
        self.assertEqual(caught.exception.code, 2)

    def test_invalid(self):
        for argv in ([], ["bogus"], ["inject"], ["inject", "nope"], ["ask", "x", "q"], ["ask", "paid-scan-diagnosis"],
                     ["ask", "paid-scan-diagnosis", "  "], ["up", "--model", " "], ["up", "--model", "a b"]):
            self.bad(argv)

    def test_valid(self):
        self.assertEqual(lab.parse_args(["up"]).model, "gpt-oss:20b")
        self.assertEqual(lab.parse_args(["inject", "pricer-down"]).scenario, "pricer-down")
        self.assertTrue(lab.parse_args(["down", "--purge"]).purge)
        self.assertEqual(lab.parse_args(["ask", "lnd-ops-runbook-agent", "hi"]).question, "hi")


if __name__ == "__main__":
    unittest.main()
