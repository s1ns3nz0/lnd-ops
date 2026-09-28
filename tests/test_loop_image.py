import importlib.util
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops'))
from loop_api import API

spec = importlib.util.spec_from_file_location('loop_release_install', ROOT / 'loop-image/install.py')
install = importlib.util.module_from_spec(spec); spec.loader.exec_module(install)


class LoopRuntimeTests(unittest.TestCase):
    def test_elf_architecture_is_checked_independently_of_oci_label(self):
        for machine in (62, 183):
            header = b'\x7fELF\x02\x01' + b'\0' * 12 + struct.pack('<H', machine)
            self.assertEqual(install.elf_machine(header), machine)
        with self.assertRaises(ValueError): install.elf_machine(b'not an ELF')

    def test_exec_format_error_is_actionable_and_logs_are_not_echoed(self):
        api = API({})
        pods = {'items': [{'metadata': {'name': 'loopd-test'}, 'status': {'containerStatuses': [
            {'name': 'loopd', 'ready': False, 'restartCount': 3,
             'state': {'waiting': {'reason': 'CrashLoopBackOff'}}}]}}]}
        with patch.object(api, 'command', return_value=pods), patch('loop_api.subprocess.run', return_value=Mock(stdout='secret-placeholder\nexec /bin/loopd: exec format error', stderr='')):
            result = api.startup_diagnostic()
        self.assertIn('CPU 아키텍처', result)
        self.assertIn('인증 파일 재생성으로 해결되지 않습니다', result)
        self.assertNotIn('secret-placeholder', result)

    def test_deployment_cannot_claim_ready_without_authenticated_api_probe(self):
        chart = (ROOT / 'charts/lnd-ops/templates/loop.yaml').read_text()
        self.assertIn('readinessProbe:', chart)
        self.assertIn('command: [loop, --loopdir=/loop, --network=testnet, getinfo]', chart)
        self.assertIn('maxSurge: 0', chart)
        installer = (ROOT / 'ops/enable-loop').read_text()
        self.assertLess(installer.index('"$repo_dir/ops/verify-loop" --ready'), installer.index('OK: Loop deployed'))


if __name__ == '__main__': unittest.main()
