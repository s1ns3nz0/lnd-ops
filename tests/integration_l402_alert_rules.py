#!/usr/bin/env python3
"""Run promtool rule tests for the opencti-l402 alert group in the pinned Prometheus image."""
import json
import os
import pathlib
import re
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]


CASES = {"opencti-l402": "l402-alert-rules.test.yaml", "opencti-l402-slo": "l402-probe-slo.test.yaml"}


def group_text(name):
    text = (REPO / "charts/monitoring-rules.yaml").read_text()
    return re.search(rf"^    - name: {name}\n.*?(?=^    - name: |\Z)", text, re.S | re.M).group(0)


def main():
    lock = json.loads((REPO / "ops/images.lock.json").read_text())["prometheus"]
    image = lock["tag"].rsplit(":", 1)[0] + "@" + lock["digest"]
    for group, fixture in CASES.items():
        with tempfile.TemporaryDirectory() as directory:
            d = pathlib.Path(directory)
            (d / "rules.yaml").write_text("groups:\n" + group_text(group))  # group indent 4 is valid YAML under a top-level key
            (d / "cases.yaml").write_text((REPO / "tests/fixtures" / fixture).read_text())
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "/bin/promtool",
                            "-v", f"{directory}:/cases:ro", image, "test", "rules", "/cases/cases.yaml"], check=True)
        print(f"PASS: {group} alert rules against pinned promtool")
    detect = re.search(r"# detect_at: (\d+)m", (REPO / "tests/fixtures/l402-probe-slo.test.yaml").read_text()).group(1)
    print(f"MEASURED: FastBurn fires {int(detect) - 70} min after the first failed probe (eval and probe interval 1 min; real jitter adds up to ~2 min)")


if __name__ == "__main__":
    main()
