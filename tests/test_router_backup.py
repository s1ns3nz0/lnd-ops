import hashlib
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'ops'))
from router_backup import CONFIRM, digest, register, status
from router_store import read


class ExternalBackupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = pathlib.Path(temp.name)
        self.root = self.directory / 'router'
        self.local = self.directory / 'local.gpg'
        self.external = self.directory / 'external.gpg'
        for path in (self.local, self.external):
            path.write_bytes(b'opaque encrypted fixture')
        checksum, identity = digest(self.local)
        self.snapshot = {'wallet': 'node', 'plain_sha256': 'a' * 64, 'cipher_sha256': checksum,
                         'backup_created_at': 100, 'local_file': identity}
        self.observe = Mock(side_effect=lambda: self.snapshot.copy())

    def test_register_and_recheck_same_ciphertext_without_decrypting(self):
        result = register(self.root, self.external, CONFIRM, self.observe)
        self.assertEqual(result['location_provenance'], 'operator-attested-external')
        self.assertFalse(result['restore_tested'])
        self.assertEqual(status(self.root, self.observe)['state'], 'current')
        self.assertEqual(self.external.read_bytes(), b'opaque encrypted fixture')

    def test_registration_requires_location_confirmation(self):
        with self.assertRaises(ValueError):
            register(self.root, self.external, '', self.observe)
        self.observe.assert_not_called()
        self.assertIsNone(read(self.root, 'backup-copy.json'))

    def test_local_file_hardlink_and_symlink_cannot_be_registered(self):
        hard = self.directory / 'hard.gpg'
        os.link(self.local, hard)
        symbolic = self.directory / 'symbolic.gpg'
        symbolic.symlink_to(self.external)
        for path in (self.local, hard, symbolic):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                register(self.root, path, CONFIRM, self.observe)

    def test_changed_channel_scb_invalidates_old_external_copy(self):
        register(self.root, self.external, CONFIRM, self.observe)
        self.snapshot['plain_sha256'] = 'b' * 64
        self.assertEqual(status(self.root, self.observe)['state'], 'unverified')

    def test_changed_wallet_or_ciphertext_cannot_reuse_registration(self):
        register(self.root, self.external, CONFIRM, self.observe)
        self.snapshot['wallet'] = 'other'
        self.assertEqual(status(self.root, self.observe)['state'], 'unverified')
        self.snapshot['wallet'] = 'node'
        self.external.write_bytes(b'tampered')
        self.assertEqual(status(self.root, self.observe)['state'], 'unverified')

    def test_missing_external_mount_is_unverified_not_missing_registration(self):
        register(self.root, self.external, CONFIRM, self.observe)
        self.external.unlink()
        self.assertEqual(status(self.root, self.observe)['state'], 'unverified')
        self.assertIsNotNone(read(self.root, 'backup-copy.json'))

    def test_source_changes_during_inspection_abort_without_record(self):
        changed = self.snapshot | {'plain_sha256': 'c' * 64}
        with self.assertRaisesRegex(ValueError, '검사 중'):
            register(self.root, self.external, CONFIRM, Mock(side_effect=[self.snapshot, changed]))
        self.assertIsNone(read(self.root, 'backup-copy.json'))

    def test_fifo_and_empty_files_rejected_without_waiting_for_writer(self):
        fifo = self.directory / 'pipe'
        os.mkfifo(fifo)
        empty = self.directory / 'empty'
        empty.touch()
        for path in (fifo, empty):
            with self.subTest(path=path), self.assertRaises(ValueError):
                digest(path)


if __name__ == '__main__':
    unittest.main()
