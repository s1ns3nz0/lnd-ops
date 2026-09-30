import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ProbeConfigTest(unittest.TestCase):
    def test_blackbox_manifest_is_pinned_and_hardened(self):
        text = (ROOT / "charts/blackbox-exporter.yaml").read_text()
        self.assertRegex(text, r"image: prom/blackbox-exporter:v[\d.]+@sha256:[0-9a-f]{64}\n")
        for needle in ("runAsNonRoot: true", "readOnlyRootFilesystem: true", "drop: [ALL]", "allowPrivilegeEscalation: false",
                       "http_2xx_health:", "lnd_state:", "tcp_connect:", "insecure_skip_verify: true",
                       'fail_if_body_not_matches_regexp: ["SERVER_ACTIVE"]', "valid_status_codes: [200]", "port: 9115"):
            self.assertIn(needle, text)

    def test_scrape_job_targets_and_modules(self):
        values = (ROOT / "charts/monitoring-values.yaml").read_text()
        job = re.search(r"- job_name: l402-probe\n(.*?)(?=      - job_name: )", values, re.S).group(1)
        self.assertIn("scrape_interval: 60s", job)
        self.assertIn("metrics_path: /probe", job)
        self.assertIn("replacement: l402-blackbox-exporter.lndops-monitoring.svc:9115", job)
        for target, component, module in (
                ("http://payment-aperture-services.opencti-paid-scan-e2e.svc:8090/health", "pricer", "http_2xx_health"),
                ("https://lnd-merchant.opencti-paid-scan-e2e.svc:8080/v1/state", "lnd_merchant", "lnd_state"),
                ("l402-aperture.opencti-paid-scan-e2e.svc:8081", "aperture", "tcp_connect")):
            self.assertIn(f"targets: [{target}]", job)
            self.assertIn(f"{{component: {component}, __param_module: {module}}}", job)

    def test_deploy_monitoring_applies_blackbox_before_rules(self):
        text = (ROOT / "ops/deploy-monitoring").read_text()
        self.assertLess(text.index("charts/blackbox-exporter.yaml"), text.index("charts/monitoring-rules.yaml"))


if __name__ == "__main__":
    unittest.main()
