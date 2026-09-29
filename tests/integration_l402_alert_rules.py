#!/usr/bin/env python3
"""Run promtool rule tests for the opencti-l402 alert group in the pinned Prometheus image."""
import json
import pathlib
import re
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]


def group_text():
    text = (REPO / "charts/monitoring-rules.yaml").read_text()
    return re.search(r"^    - name: opencti-l402\n.*?(?=^    - name: |\Z)", text, re.S | re.M).group(0)


def main():
    lock = json.loads((REPO / "ops/images.lock.json").read_text())["prometheus"]
    image = lock["tag"].rsplit(":", 1)[0] + "@" + lock["digest"]
    with tempfile.TemporaryDirectory() as directory:
        d = pathlib.Path(directory)
        (d / "rules.yaml").write_text("groups:\n" + group_text())  # group indent 4 is valid YAML under a top-level key
        (d / "cases.yaml").write_text((REPO / "tests/fixtures/l402-alert-rules.test.yaml").read_text())
        subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "/bin/promtool",
                        "-v", f"{directory}:/cases:ro", image, "test", "rules", "/cases/cases.yaml"], check=True)
    print("PASS: opencti-l402 alert rules against pinned promtool")


if __name__ == "__main__":
    main()
