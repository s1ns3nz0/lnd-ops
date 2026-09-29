import base64
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "ops/provision-paid-scan-diagnostics"
U1 = "0F8FAD5B-D9CB-469F-A165-70867728950E"
U2 = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
SERVER, CLIENT = "order-diagnostics-server.secret.json", "paid-scan-diagnostics-client.secret.json"


def sh(*args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = pathlib.Path(self.tmp.name) / "out"

    def run_script(self, *extra, tenants=(U1, U2)):
        args = [sys.executable, str(SCRIPT), "--out", str(self.out)]
        for t in tenants:
            args += ["--tenant", t]
        return sh(*args, *extra)

    def load(self):
        def data(name):
            doc = json.loads((self.out / name).read_text())
            return doc, {k: base64.b64decode(v) for k, v in doc["data"].items()}
        return data(SERVER), data(CLIENT)

    def test_outputs(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted([SERVER, CLIENT]))
        for p in self.out.iterdir():
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        (sdoc, s), (cdoc, c) = self.load()
        self.assertEqual((sdoc["kind"], sdoc["metadata"], sdoc["type"]),
                         ("Secret", {"name": "order-diagnostics-server", "namespace": "opencti-paid-scan-e2e"}, "Opaque"))
        self.assertEqual((cdoc["kind"], cdoc["metadata"]),
                         ("Secret", {"name": "paid-scan-diagnostics-client", "namespace": "lndops-agent"}))
        self.assertEqual(sorted(s), ["tenants.allowlist", "tls.crt", "tls.key", "token.sha256"])
        self.assertEqual(sorted(c), ["ca.crt", "token"])
        token = c["token"].decode()
        self.assertEqual(s["token.sha256"].decode(), hashlib.sha256(token.encode()).hexdigest() + "\n")
        self.assertEqual(s["tenants.allowlist"].decode(), U1.lower() + "\n" + U2 + "\n")
        for text in (r.stdout, r.stderr):
            self.assertNotIn(token, text)
            self.assertNotIn(s["token.sha256"].decode().strip(), text)
        self.assertIn("kubectl apply -f", r.stdout)

    def test_certs(self):
        self.assertEqual(self.run_script().returncode, 0)
        (_, s), (_, c) = self.load()
        d = pathlib.Path(self.tmp.name)
        for name, blob in (("tls.crt", s["tls.crt"]), ("tls.key", s["tls.key"]), ("ca.crt", c["ca.crt"])):
            (d / name).write_bytes(blob)
        v = sh("openssl", "verify", "-CAfile", str(d / "ca.crt"), str(d / "tls.crt"))
        self.assertEqual(v.returncode, 0, v.stderr)
        san = sh("openssl", "x509", "-noout", "-ext", "subjectAltName", "-in", str(d / "tls.crt")).stdout
        for n in ("order-diagnostics.opencti-paid-scan-e2e.svc", "order-diagnostics.opencti-paid-scan-e2e.svc.cluster.local"):
            self.assertIn("DNS:" + n, san)
        bc = lambda f: sh("openssl", "x509", "-noout", "-ext", "basicConstraints", "-in", str(d / f)).stdout
        self.assertIn("CA:TRUE", bc("ca.crt"))
        self.assertIn("CA:FALSE", bc("tls.crt"))
        crt_pub = sh("openssl", "x509", "-noout", "-pubkey", "-in", str(d / "tls.crt")).stdout
        key_pub = sh("openssl", "pkey", "-pubout", "-in", str(d / "tls.key")).stdout
        self.assertTrue(crt_pub)
        self.assertEqual(crt_pub, key_pub)
        pem = "".join(base64.b64decode(v).decode(errors="ignore") + p.read_text()
                      for p in self.out.iterdir() for v in json.loads(p.read_text())["data"].values())
        blocks = pem.count("-----BEGIN ") and len(re.findall(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", pem))
        self.assertEqual(blocks, 1)  # the server key only

    def test_invalid_tenant(self):
        r = self.run_script(tenants=("not-a-uuid",))
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL:", r.stderr)
        self.assertFalse(self.out.exists())
        self.assertNotEqual(self.run_script(tenants=()).returncode, 0)

    def test_existing_dir(self):
        self.out.mkdir()
        (self.out / SERVER).write_text("old")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.out / SERVER).read_text(), "old")
        self.assertEqual(self.run_script("--force").returncode, 0)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted([SERVER, CLIENT]))
        self.assertNotEqual((self.out / SERVER).read_text(), "old")

    def test_force_refuses_unrelated_entries(self):
        self.out.mkdir()
        (self.out / "keep").write_text("x")
        (self.out / SERVER).write_text("old")
        r = self.run_script("--force")
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL:", r.stderr)
        self.assertEqual((self.out / "keep").read_text(), "x")
        self.assertEqual((self.out / SERVER).read_text(), "old")

    def test_force_refuses_symlink_and_file(self):
        target = pathlib.Path(self.tmp.name) / "target"
        target.mkdir()
        (target / "keep").write_text("x")
        self.out.symlink_to(target)
        self.assertEqual(self.run_script("--force").returncode, 1)
        self.assertEqual((target / "keep").read_text(), "x")
        self.out.unlink()
        self.out.write_text("f")
        self.assertEqual(self.run_script("--force").returncode, 1)
        self.assertEqual(self.out.read_text(), "f")


class ChartPolicyTest(unittest.TestCase):
    def test_model_config_pinned(self):
        text = (ROOT / "charts/agent/templates/paid-scan.yaml").read_text()
        self.assertIn("modelConfig: default-model-config", text)
        self.assertNotIn(".Values.paidScan.modelConfig", text)
        self.assertNotIn("modelConfig", (ROOT / "charts/agent/values.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
