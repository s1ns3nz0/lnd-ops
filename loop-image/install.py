"""Install checksum-pinned official Loop release binaries, validating ELF ISA."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
from urllib.request import urlopen


def elf_machine(binary):
    if len(binary) < 20 or binary[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected a 64-bit little-endian Linux ELF binary')
    return struct.unpack('<H', binary[18:20])[0]


def main(arch, destination):
    lock = json.loads(Path(__file__).with_name('releases.json').read_text())
    if arch not in ('amd64', 'arm64'):
        raise ValueError('Only amd64 and arm64 are supported')
    version = lock['version']
    name = f'loop-linux-{arch}-{version}'
    url = f'https://github.com/lightninglabs/loop/releases/download/{version}/{name}.tar.gz'
    with urlopen(url, timeout=90) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != lock['archives'][arch]:
        raise ValueError('Official Loop release checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
        for binary in ('loop', 'loopd'):
            member = tar.getmember(f'{name}/{binary}')
            if not member.isfile():
                raise ValueError('Expected a regular release binary')
            content = tar.extractfile(member).read()
            if elf_machine(content) != {'amd64': 62, 'arm64': 183}[arch]:
                raise ValueError(f'{binary}: ELF architecture does not match {arch}')
            target = Path(destination) / binary
            target.write_bytes(content)
            target.chmod(0o755)
    print(f'Installed verified {version} linux/{arch} binaries')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
