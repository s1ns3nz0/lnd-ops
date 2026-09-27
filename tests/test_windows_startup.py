import contextlib
import importlib.machinery
import io
import os
import pathlib
import subprocess
import unittest
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
startup = importlib.machinery.SourceFileLoader('windows_startup', str(REPO / 'ops/windows-router-startup')).load_module()


class WslStartupTests(unittest.TestCase):
    def setUp(self):
        self.system = patch.object(startup.platform, 'system', return_value='Linux').start()
        patch.object(startup.platform, 'release', return_value='microsoft-standard-WSL2').start()
        patch.dict(os.environ, {'WSL_DISTRO_NAME': 'Ubuntu'}).start()
        patch.object(startup.shutil, 'which', return_value='/windows/powershell.exe').start()
        self.output = patch.object(startup.subprocess, 'check_output', side_effect=['miata\n', 'C:\\repo\\script.ps1\n']).start()
        self.run = patch.object(startup.subprocess, 'run').start()
        self.addCleanup(patch.stopall)

    def test_default_only_previews_and_passes_arguments_without_shell(self):
        startup.main([])
        self.assertEqual(self.run.call_count, 1)
        args = self.run.call_args.args[0]
        self.assertEqual(args[-6:], ['-Mode', 'Preview', '-DistroName', 'Ubuntu', '-LinuxUser', 'miata'])
        self.assertNotIn('shell', self.run.call_args.kwargs)

    def test_unapproved_install_does_not_invoke_any_process(self):
        with self.assertRaises(ValueError):
            startup.main(['--mode', 'install'])
        self.run.assert_not_called()
        self.output.assert_not_called()

    def test_install_requires_all_three_enabled_services(self):
        startup.main(['--mode', 'install', '--confirm', 'INSTALL WSL STARTUP'])
        calls = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual([command[-1] for command in calls[:-1]], [
            'k3s.service', 'lnd-ops-router-monitor.service', 'lnd-ops-router-refresh.service'])
        self.assertEqual(calls[-1][-2:], ['-Confirm', 'INSTALL WSL STARTUP'])

    def test_missing_service_blocks_windows_registration(self):
        self.run.side_effect = subprocess.CalledProcessError(1, 'systemctl')
        with self.assertRaises(subprocess.CalledProcessError):
            startup.main(['--mode', 'install', '--confirm', 'INSTALL WSL STARTUP'])
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.run.call_args.args[0][0], 'systemctl')

    def test_ssh_session_discovers_current_distribution(self):
        with patch.dict(os.environ, {'WSL_DISTRO_NAME': ''}):
            self.output.side_effect = ['\\\\wsl.localhost\\Ubuntu\\\n', 'miata\n', 'C:\\repo\\script.ps1\n']
            startup.main(['--mode', 'status'])
        self.assertIn('Ubuntu', self.run.call_args.args[0])

    def test_invalid_distro_does_not_reach_windows(self):
        with patch.dict(os.environ, {'WSL_DISTRO_NAME': 'Ubuntu;malicious'}), self.assertRaises(ValueError):
            startup.main([])
        self.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
