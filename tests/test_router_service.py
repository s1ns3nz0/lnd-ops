import pathlib
import plistlib
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ops"))
from router_service import configuration, render_linux, render_macos


class ServiceTests(unittest.TestCase):
    def helper(self, name):
        return runpy.run_path(str(pathlib.Path(__file__).resolve().parents[1] / "ops/router-service"))[name]

    def config(self, repo="/repo with spaces/$fund%20"):
        return configuration(repo, "/usr/bin/python3", "/home/user", "/home/user/.local/state",
                             "/home/user/.local/state/lnd-ops/kubeconfig", "/usr/local/bin:/usr/bin:/bin", "user")

    def test_linux_escapes_systemd_expansion_and_runs_unprivileged(self):
        rendered = render_linux(self.config())
        self.assertIn('"/repo with spaces/$$fund%%20/ops/router-monitor"', rendered)
        self.assertIn("User=user\n", rendered)
        self.assertIn("KillMode=control-group", rendered)
        self.assertNotIn("ExecStart=/bin/sh", rendered)

    def test_macos_roundtrips_literal_arguments_and_only_allowlisted_environment(self):
        document = plistlib.loads(render_macos(self.config()).encode())
        self.assertEqual(document["ProgramArguments"], ["/usr/bin/python3", "/repo with spaces/$fund%20/ops/router-monitor"])
        self.assertEqual(set(document["EnvironmentVariables"]), {"HOME", "XDG_STATE_HOME", "PATH", "KUBECONFIG"})
        self.assertEqual(document["Umask"], 0o077)

    def test_macos_vm_start_is_explicitly_selected_in_service_definition(self):
        config = self.config()
        config["start_vm"] = True
        document = plistlib.loads(render_macos(config).encode())
        self.assertTrue(document["ProgramArguments"][1].endswith("/ops/router-vm-start"))

    def test_invalid_path_root_and_directive_injection_are_rejected(self):
        for repo in ("relative", "/repo\nUser=root", "/repo\x00"):
            with self.assertRaises(ValueError):
                self.config(repo)
        with self.assertRaises(ValueError):
            configuration("/repo", "/bin/python", "/root", "/state", "/kube", "/bin", "root")
        with self.assertRaises(ValueError):
            configuration("/repo", "/bin/python", "/home/u", "/state", "/kube", "/bin:", "u")

    def test_unmanaged_file_and_symlink_are_not_replaced(self):
        helper = self.helper("existing_target")
        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / "unit"
            target.write_text("[Service]\nExecStart=/bin/true\n")
            with self.assertRaises(ValueError):
                helper(target, False)
            alias = pathlib.Path(directory) / "alias"
            alias.symlink_to(target)
            with self.assertRaises(ValueError):
                helper(alias, False)
            target.write_text(render_linux(self.config()))
            helper(target, False)

    def test_install_requires_exact_confirmation_before_service_mutation(self):
        main = self.helper("main")
        install = Mock()
        with patch.dict(main.__globals__, install=install), patch("platform.system", return_value="Linux"):
            with self.assertRaisesRegex(ValueError, "승인"):
                main(["--install"])
            with self.assertRaisesRegex(ValueError, "승인"):
                main(["--install", "--platform", "macos", "--confirm", "INSTALL ROUTER MONITOR"])
        install.assert_not_called()

    def test_linux_install_stops_if_privileged_file_install_fails(self):
        install = self.helper("install")
        run = Mock(side_effect=OSError("sudo denied"))
        with patch.dict(install.__globals__, run=run, existing_target=Mock()), patch("os.getuid", return_value=1000):
            with self.assertRaisesRegex(OSError, "sudo denied"):
                install(self.config(), "linux", render_linux(self.config()))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[:2], ("sudo", "install"))

    def test_macos_install_replaces_only_its_agent_then_bootstraps(self):
        install = self.helper("install")
        commands = Mock()
        with tempfile.TemporaryDirectory() as directory:
            config = self.config()
            config["environment"]["HOME"] = directory
            with patch.dict(install.__globals__, run=commands), patch("os.getuid", return_value=1000), \
                    patch("subprocess.run", return_value=Mock(returncode=0)):
                install(config, "macos", render_macos(config))
            self.assertEqual(commands.call_args_list[0].args[:2], ("launchctl", "bootout"))
            self.assertEqual(commands.call_args_list[1].args[:2], ("launchctl", "bootstrap"))
            target = pathlib.Path(directory) / "Library/LaunchAgents/org.lndops.router-monitor.plist"
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(plistlib.loads(target.read_bytes())["EnvironmentVariables"]["HOME"], directory)


if __name__ == "__main__":
    unittest.main()
