import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("diag", ROOT / "agent/paid_scan_diagnostics.py")
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)

PLAYBOOK = "docs/playbooks/opencti-l402-funnel.md"
EXPECTED = {
    "OpenCTIL402InvoiceIssuanceFailing": "critical",
    "OpenCTIL402SecretStoreFailing": "critical",
    "OpenCTIL402RequestsWithoutInvoice": "critical",
    "OpenCTIL402MetricsAbsent": "warning",
}


def group():
    text = (ROOT / "charts/monitoring-rules.yaml").read_text()
    m = re.search(r"^    - name: opencti-l402\n(.*?)(?=^    - name: |\Z)", text, re.S | re.M)
    assert m, "opencti-l402 group missing"
    return m.group(1)


class L402AlertRules(unittest.TestCase):
    def test_alerts_and_severities(self):
        rules = re.findall(r"- alert: (\S+)\n.*?severity: (\w+)", group(), re.S)
        self.assertEqual(dict(rules), EXPECTED)
        self.assertEqual(len(rules), 4)

    def test_every_alert_links_existing_playbook(self):
        self.assertEqual(group().count(f"playbook: {PLAYBOOK}"), 4)
        self.assertTrue((ROOT / PLAYBOOK).is_file())

    def test_threshold_matches_diagnostics(self):
        self.assertIn(f">= {diag.NO_INVOICE_MIN}", group())

    def test_no_macaroon_valid(self):
        self.assertNotIn("macaroon_valid", group())


if __name__ == "__main__":
    unittest.main()
