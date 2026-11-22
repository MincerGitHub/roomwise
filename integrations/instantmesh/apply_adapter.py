"""Apply the reviewed Roomwise patch to a clean, pinned InstantMesh checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def apply(checkout):
    root = checkout.resolve(strict=True)
    manifest = json.loads((HERE / 'adapter-manifest.json').read_text(encoding='utf-8'))
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    if current != manifest['base_commit']:
        raise RuntimeError('Use the InstantMesh commit specified in adapter-manifest.json; no files were changed.')
    before = True
    after = True
    for name, hashes in manifest['modified_files'].items():
        path = (root / name).resolve()
        path.relative_to(root)
        checksum = digest(path.read_bytes())
        before &= checksum == hashes['before_sha256']
        after &= checksum == hashes['after_sha256']
    for name, checksum in manifest['new_files'].items():
        path = (root / name).resolve()
        path.relative_to(root)
        source = HERE / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('Adapter source checksum mismatch: ' + name)
        before &= not path.exists()
        after &= path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum
    if after:
        print('Roomwise adapter is already installed; no files changed.')
        return
    if not before:
        raise RuntimeError('Target files contain other changes; preserve them and use a clean checkout. No files changed.')
    patch = str(HERE / 'roomwise-adapter.patch')
    subprocess.run(['git', 'apply', '--check', patch], cwd=root, check=True)
    subprocess.run(['git', 'apply', patch], cwd=root, check=True)
    for name in manifest['new_files']:
        shutil.copyfile(HERE / name, root / name)
    for name, hashes in manifest['modified_files'].items():
        if digest((root / name).read_bytes()) != hashes['after_sha256']:
            raise RuntimeError('Patched file checksum mismatch: ' + name)
    print('Roomwise adapter installed. Model weights and Python packages were not changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path, help='A separate TencentARC/InstantMesh checkout')
    apply(parser.parse_args().checkout)
