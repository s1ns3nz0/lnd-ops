"""The L402 dashboard must show the same numbers the agent and alerts use."""
import importlib.util
import json
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('psd', REPO / 'agent/paid_scan_diagnostics.py')
psd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(psd)
DASH = json.loads((REPO / 'charts/dashboards/opencti-l402.json').read_text())
RULES = (REPO / 'charts/monitoring-rules.yaml').read_text()
EXPRS = [t['expr'] for p in DASH['panels'] for t in p.get('targets', [])]
ALLOWED = {'aperture_l402_mint_total', 'aperture_l402_verify_total', 'probe_success', 'l402_probe:up',
           'l402_probe:error_ratio_5m', 'l402_probe:error_ratio_30m', 'l402_probe:error_ratio_1h',
           'l402_probe:error_ratio_6h', 'ALERTS', 'up'}
FUNCS = {'sum', 'count', 'max', 'min', 'avg_over_time', 'increase', 'vector', 'by', 'or', 'offset', 'without'}


def alert_burn(name):
    expr = re.search(rf'alert: {name}\n\s+expr: (.+)', RULES).group(1)
    return {float(n) for n in re.findall(r'\(([\d.]+) \* 0\.005\)', expr)}


class L402DashboardTest(unittest.TestCase):
    def test_funnel_queries_verbatim(self):
        skip = {'PROBE_ERR_1H', 'PROBE_ERR_5M', 'PROBE_COMPONENTS'}
        for name, query in psd.FUNNEL_QUERIES.items():
            if name not in skip:
                self.assertIn(query, EXPRS, name)

    def test_only_known_metrics(self):
        for expr in EXPRS:
            bare = re.sub(r'"[^"]*"|by \([^)]*\)|offset \w+|\{[^}]*\}|\[[^\]]*\]', '', expr)  # drop label values, matchers, ranges
            for name in re.findall(r'[A-Za-z_:][A-Za-z0-9_:]*', bare):
                if name not in FUNCS:
                    self.assertIn(name, ALLOWED, expr)

    def test_burn_thresholds_match_alerts(self):
        burn = next(p for p in DASH['panels'] if p['title'] == 'Burn rate by window')
        values = {s['value'] for s in burn['fieldConfig']['defaults']['thresholds']['steps'] if s['value']}
        self.assertEqual(values, alert_burn('OpenCTIL402ProbeFastBurn') | alert_burn('OpenCTIL402ProbeSlowBurn'))
        self.assertEqual(max(values), psd.FAST_BURN)


if __name__ == '__main__':
    unittest.main()
