"""Build and smoke-test the native Loop release image; import only on request."""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def image_tag(arch):
    sources = b''.join((ROOT / 'loop-image' / name).read_bytes() for name in ('Dockerfile', 'install.py', 'releases.json'))
    return f'localhost/lnd-ops-loop:{hashlib.sha256(sources).hexdigest()[:16]}-{arch}'


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def build(arch):
    image = image_tag(arch)
    with tempfile.TemporaryDirectory(prefix='loop-build-') as directory:
        metadata = Path(directory) / 'metadata.json'
        run(['docker', 'buildx', 'build', '--platform', 'linux/' + arch, '--provenance=false', '--metadata-file', str(metadata), '--load', '-t', image, str(ROOT / 'loop-image')], stdout=__import__('sys').stderr)
        digest = json.loads(metadata.read_text())['containerimage.digest']
    # Do not trust OCI platform metadata or emulation alone. Verify e_machine
    # inside the image as well as both executable entry points.
    code = "import struct,pathlib; " + f"expected={dict(amd64=62,arm64=183)[arch]}; " + "assert all(struct.unpack('<H',pathlib.Path('/usr/local/bin/'+n).read_bytes()[18:20])[0]==expected for n in ('loop','loopd'))"
    run(['docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/' + arch,
         '--entrypoint', 'python3', image, '-c', code])
    for executable in ('loopd', 'loop'):
        run(['docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/' + arch,
             '--entrypoint', executable, image, '--version'], stdout=__import__('sys').stderr)
    return image, 'localhost/lnd-ops-loop@' + digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arch', choices=['arm64', 'amd64'], default={'arm64':'arm64', 'aarch64':'arm64', 'x86_64':'amd64', 'amd64':'amd64'}.get(platform.machine()))
    parser.add_argument('--tag-only', action='store_true')
    parser.add_argument('--load-k3s', action='store_true')
    args = parser.parse_args()
    if not args.arch:
        parser.error('Unsupported architecture')
    if args.tag_only:
        print(image_tag(args.arch)); return
    image, pinned = build(args.arch)
    if args.load_k3s:
        import os
        if platform.system() == 'Darwin':
            command = ['limactl', 'shell', os.environ.get('LND_OPS_VM_NAME', 'lnd-ops-k3s'), '--', 'sudo', 'k3s', 'ctr', 'images', 'import', '-']
        elif platform.system() == 'Linux':
            command = ['sudo', 'k3s', 'ctr', 'images', 'import', '-']
        else:
            parser.error('K3s import requires macOS/Lima or Linux')
        local_prefix = command[:-4]
        os.environ.setdefault('KUBECONFIG', str(Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'lnd-ops/kubeconfig'))
        local_uid = subprocess.check_output(local_prefix + ['kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', 'get', 'namespace', 'kube-system', '-o', 'jsonpath={.metadata.uid}'], text=True).strip()
        selected_uid = subprocess.check_output(['kubectl', 'get', 'namespace', 'kube-system', '-o', 'jsonpath={.metadata.uid}'], text=True).strip()
        if not local_uid or local_uid != selected_uid:
            raise RuntimeError('Selected kubeconfig is not the local K3s cluster; refusing image import')
        nodes = json.loads(subprocess.check_output(['kubectl', 'get', 'nodes', '-o', 'json'], text=True))['items']
        if len(nodes) != 1 or nodes[0]['status']['nodeInfo']['architecture'] != args.arch:
            raise RuntimeError('Local image import requires one node matching the image architecture')
        tag_command = command[:-3] + ['images', 'tag', '--force', image, pinned]
        with subprocess.Popen(['docker', 'save', image], stdout=subprocess.PIPE) as source:
            run(command, stdin=source.stdout, stdout=__import__('sys').stderr)
            source.stdout.close()
            if source.wait():
                raise RuntimeError('Image export failed')
        listing = subprocess.check_output(command[:-3] + ['images', 'list', 'name==' + image], text=True)
        imported = [row.split()[2] for row in listing.splitlines() if row.split() and row.split()[0] == image]
        if imported != [pinned.rsplit('@', 1)[1]]:
            raise RuntimeError('Imported manifest digest differs from the verified build; refusing digest alias')
        run(tag_command, stdout=__import__('sys').stderr)
    print(pinned)


if __name__ == '__main__': main()
