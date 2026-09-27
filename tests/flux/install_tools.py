"""Install checksum-locked Linux CI tools into the repository cache only."""
import hashlib
from pathlib import Path
import platform
import tarfile
from urllib.request import urlopen

if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
    raise SystemExit('This CI installer requires Linux amd64')
root = Path(__file__).resolve().parents[2] / '.cache/flux-bin'
root.mkdir(parents=True, exist_ok=True)
assets = {
    'kind': ('https://github.com/kubernetes-sigs/kind/releases/download/v0.31.0/kind-linux-amd64', 'eb244cbafcc157dff60cf68693c14c9a75c4e6e6fedaf9cd71c58117cb93e3fa'),
    'kubectl': ('https://dl.k8s.io/release/v1.35.0/bin/linux/amd64/kubectl', 'a2e984a18a0c063279d692533031c1eff93a262afcc0afdc517375432d060989'),
    'helm.tgz': ('https://get.helm.sh/helm-v4.1.4-linux-amd64.tar.gz', '70b2c30a19da4db264dfd68c8a3664e05093a361cefd89572ffb36f8abfa3d09'),
}
for name, (url, expected) in assets.items():
    data = urlopen(url, timeout=60).read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f'checksum mismatch: {name}')
    (root / name).write_bytes(data)
with tarfile.open(root / 'helm.tgz') as archive:
    (root / 'helm').write_bytes(archive.extractfile('linux-amd64/helm').read())
for name in ('kind', 'kubectl', 'helm'):
    (root / name).chmod(0o755)
print(root)
