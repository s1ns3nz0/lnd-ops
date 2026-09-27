"""Verify an operator-designated external encrypted SCB copy without copying it."""
import hashlib
import os
import pathlib
import re
import stat
import subprocess
import time

from router_rpc import call, require_testnet, environment
from router_store import operation_lock, read, write

CONFIRM = 'VERIFY EXTERNAL ENCRYPTED SCB COPY'


def digest(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 64 * 1024 * 1024:
            raise ValueError('암호화 SCB 사본은 64 MiB 이하의 비어 있지 않은 일반 파일이어야 합니다')
        result = hashlib.sha256()
        total = 0
        for chunk in iter(lambda: stream.read(65536), b''):
            total += len(chunk)
            if total > 64 * 1024 * 1024:
                raise ValueError('검사 도중 SCB 사본 크기가 제한을 초과했습니다')
            result.update(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('검사 도중 외부 사본이 변경되었습니다')
        return result.hexdigest(), (before.st_dev, before.st_ino)


def local_snapshot():
    info = call('getinfo')
    require_testnet(info)
    helper = pathlib.Path(__file__).with_name('backup-status-encrypted')
    checked = subprocess.run([str(helper), 'testnet', 'lnd-0', '--read-only'],
                             env=environment(), text=True, capture_output=True, timeout=60)
    if checked.returncode:
        raise ValueError('현재 SCB의 암호화 백업을 먼저 갱신하세요: ' + (checked.stderr or checked.stdout).strip())
    directory = pathlib.Path.home() / 'lnd-ops-backups-encrypted/testnet/lnd-0'
    fields = (directory / '.last-success').read_text().split()
    if len(fields) != 4 or fields[3] != 'gpg-symmetric-v1' or not fields[0].isdigit() or any(
            not re.fullmatch(r'[0-9a-f]{64}', value) for value in fields[1:3]):
        raise ValueError('암호화 SCB 전송 기록이 잘못되었습니다')
    checksum, identity = digest(directory / 'channel.backup.gpg')
    if checksum != fields[2]:
        raise ValueError('암호화 SCB와 전송 기록이 다릅니다')
    return {'wallet': info['identity_pubkey'], 'plain_sha256': fields[1], 'cipher_sha256': checksum,
            'backup_created_at': int(fields[0]), 'local_file': identity}


def inspect(path, observe=local_snapshot):
    before = observe()
    checksum, identity = digest(path)
    if identity == tuple(before['local_file']):
        raise ValueError('현재 호스트 백업 파일 자체를 외부 사본으로 등록할 수 없습니다')
    if checksum != before['cipher_sha256']:
        raise ValueError('외부 사본이 현재 암호화 SCB와 다릅니다')
    after = observe()
    if before != after:
        raise ValueError('검사 중 지갑·SCB·암호화 백업이 변경됐습니다. 다시 확인하세요')
    return {key: value for key, value in before.items() if key != 'local_file'}


def register(root, path, confirmation, observe=local_snapshot):
    if confirmation != CONFIRM:
        raise ValueError('다른 장치 또는 외부 저장소에 보관한 사본이라는 확인이 필요합니다')
    path = pathlib.Path(path).expanduser().absolute()
    with operation_lock(root):
        verified = inspect(path, observe)
        record = {'schema': 'lnd-ops/router-backup-copy/v1', **verified, 'path': str(path),
                  'verified_at': time.time(), 'location_provenance': 'operator-attested-external',
                  'restore_tested': False}
        write(root, 'backup-copy.json', record)
        return record


def status(root, observe=local_snapshot):
    try:
        record = read(root, 'backup-copy.json')
        if record is None:
            return {'state': 'missing', 'message': '등록한 외부 SCB 사본이 없습니다', 'restore_tested': False}
        if not isinstance(record, dict) or record.get('schema') != 'lnd-ops/router-backup-copy/v1' or record.get('location_provenance') != 'operator-attested-external':
            raise ValueError('외부 사본 기록이 잘못되었습니다')
        verified = inspect(pathlib.Path(record['path']), observe)
        if any(verified[field] != record[field] for field in ('wallet', 'plain_sha256', 'cipher_sha256')):
            raise ValueError('등록 이후 지갑 또는 SCB가 변경됐습니다. 새 사본을 확인하세요')
        return {'state': 'current', 'checked_at': time.time(), 'message': '현재 SCB와 외부 암호화 사본 일치',
                'location_provenance': 'operator-attested-external', 'restore_tested': False}
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {'state': 'unverified', 'message': str(exc), 'restore_tested': False}
