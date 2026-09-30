#!/usr/bin/env python3
"""Evaluate the actual Router diagnostic PromQL using the pinned Prometheus image."""
import importlib.util
import json
import os
import pathlib
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gateway", REPO / "agent/runbook_gateway.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def main():
    tests = []
    for name, (metric, job, minimum) in gateway.ROUTER_SIGNALS.items():
        up = f'up{{namespace="lnd-testnet",service="lnd-0",job="{job}"}}'
        expression = gateway.router_signal_query(metric, job)
        for case, samples, evaluation, expected in (
            ("fresh_idle", [(metric, f"{minimum}+0x5"), (up, "1+0x5")], "5m", minimum),
            ("observed_zero", [(metric, "0+0x5"), (up, "1+0x5")], "5m", 0),
            ("exporter_down", [(metric, f"{minimum}+0x5"), (up, "0+0x5")], "5m", None),
            ("stale_metric", [(metric, str(minimum)), (up, "1+0x5")], "3m", None),
            ("stale_exporter", [(metric, f"{minimum}+0x5"), (up, "1")], "3m", None),
            ("wrong_namespace", [(metric.replace('lnd-testnet', 'lnd-regtest'), f"{minimum}+0x5"), (up, "1+0x5")], "5m", None),
            ("wrong_service", [(metric.replace('lnd-0', 'lnd-1'), f"{minimum}+0x5"), (up, "1+0x5")], "5m", None),
        ):
            tests.append({"name": name + "/" + case, "interval": "1m",
                          "input_series": [{"series": series, "values": values} for series, values in samples],
                          "promql_expr_test": [{"expr": expression, "eval_time": evaluation,
                                                "exp_samples": [] if expected is None else [{"labels": "{}", "value": expected}]}]})
    lock = json.loads((REPO / 'ops/images.lock.json').read_text())["prometheus"]
    image = lock["tag"].rsplit(":", 1)[0] + "@" + lock["digest"]
    with tempfile.TemporaryDirectory() as directory:
        pathlib.Path(directory, "cases.json").write_text(json.dumps({"rule_files": [], "evaluation_interval": "1m", "tests": tests}))
        subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "/bin/promtool",
                        "-v", directory + ":/cases:ro", image, "test", "rules", "/cases/cases.json"], check=True)
    print(f"PASS: {len(tests)} Router diagnostic PromQL cases against pinned Prometheus")


if __name__ == "__main__":
    main()
