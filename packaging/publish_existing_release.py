#!/usr/bin/env python3
"""Publish the five verified rebuilds to the existing v1.0.0 release.

No version/tag creation or movement. Existing assets are backed up before clobber.
On an upload failure, restore every attempted asset from the backup (best effort).
GitHub does not offer an atomic multi-asset replacement API.
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

TAG = 'v1.0.0'
REPOSITORY = 'vesvese55x/IDM-LINUX'
NAMES = [
    'IDM-LINUX-1.0.0-x86_64.AppImage',
    'idm-linux_1.0.0_all.deb',
    'idm-linux-1.0.0-1.noarch.rpm',
    'idm-linux-1.0.0-1-any.pkg.tar.zst',
    'IDM-SEMO-1.0.0-x86_64.exe',
]


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify(directory):
    result = {}
    magic = [b'\x7fELF', b'!<arch>\n', b'\xed\xab\xee\xdb', b'\x28\xb5\x2f\xfd', b'MZ']
    for name, signature in zip(NAMES, magic):
        path = directory / name
        if not path.is_file() or path.stat().st_size < 1024:
            raise ValueError('Missing/empty package: ' + name)
        with path.open('rb') as stream:
            header = stream.read(4096)
            if not header.startswith(signature):
                raise ValueError('Invalid package signature: ' + name)
            if name.endswith('.exe'):
                offset = struct.unpack_from('<I', header, 0x3c)[0]
                stream.seek(offset)
                pe = stream.read(100)
                if pe[:4] != b'PE\0\0' or struct.unpack_from('<H', pe, 4)[0] != 0x8664 or struct.unpack_from('<H', pe, 24+68)[0] != 2:
                    raise ValueError('Windows EXE must be AMD64 GUI: ' + name)
        result[name] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}
    return result


def run(*args, output=False):
    return subprocess.check_output(list(args), text=True) if output else subprocess.check_call(list(args))


def publish(directory, backup):
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise RuntimeError('Publication is restricted to the authorized repository Actions runner')
    manifest = verify(directory)
    release = json.loads(run('gh', 'api', f'repos/{REPOSITORY}/releases/tags/{TAG}', output=True))
    if release.get('immutable'):
        raise RuntimeError('Existing release is immutable. No assets were changed.')
    existing = {a['name']: a for a in release.get('assets', [])}
    if not all(name in existing for name in NAMES):
        raise RuntimeError('Expected five existing assets were not found; refusing partial replacement')
    backup.mkdir(parents=True, exist_ok=True)
    old_manifest = {}
    for name in NAMES:
        run('gh', 'release', 'download', TAG, '--repo', REPOSITORY, '--pattern', name, '--dir', str(backup))
        path = backup / name
        if path.stat().st_size != existing[name]['size']:
            raise RuntimeError('Backup size mismatch: ' + name)
        digest = sha256(path)
        upstream = existing[name].get('digest') or ''
        if upstream.startswith('sha256:') and upstream[7:] != digest:
            raise RuntimeError('Backup digest mismatch: ' + name)
        old_manifest[name] = {'bytes': path.stat().st_size, 'sha256': digest}
    (backup / 'before-publication.json').write_text(json.dumps(old_manifest, indent=2))
    (directory / 'build-sha256.json').write_text(json.dumps(manifest, indent=2))
    attempted = []
    try:
        for name in NAMES:
            attempted.append(name)
            run('gh', 'release', 'upload', TAG, str(directory / name), '--repo', REPOSITORY, '--clobber')
        # Re-download each published asset; do not trust upload exit status alone.
        verified = directory / 'published-verification'
        verified.mkdir()
        for name in NAMES:
            run('gh', 'release', 'download', TAG, '--repo', REPOSITORY, '--pattern', name, '--dir', str(verified))
            if sha256(verified / name) != manifest[name]['sha256']:
                raise RuntimeError('Published asset digest mismatch: ' + name)
    except Exception:
        errors = []
        for name in reversed(attempted):
            try:
                run('gh', 'release', 'upload', TAG, str(backup / name), '--repo', REPOSITORY, '--clobber')
            except Exception as exc:
                errors.append(name + ': ' + str(exc))
        if errors:
            raise RuntimeError('Rollback incomplete; protected backup artifact required: ' + '; '.join(errors))
        raise
    print('EXISTING_FIVE_RELEASE_ASSETS_UPDATED_AND_SHA256_VERIFIED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--backup', type=Path, default=Path('release-backup'))
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps(verify(args.directory), indent=2))
    else:
        publish(args.directory, args.backup)
