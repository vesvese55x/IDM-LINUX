#!/usr/bin/env python3
"""Replace only the authoritative BAT's CAB payload, preserving its setup prefix.

Example: python packaging/windows/repack_bat.py installer.bat rebuilt.cab
Build the flat CAB with gcab -cz or Windows makecab first. No version is modified.
"""
import argparse
import base64
import hashlib
from pathlib import Path


def repack(bat: Path, cabinet: Path):
    with cabinet.open('rb') as source:
        if source.read(4) != b'MSCF':
            raise ValueError('Not a Microsoft CAB file')
    output = bat.with_name(bat.name + '.repacking')
    found = False
    try:
        with bat.open('rb') as source, output.open('wb') as target:
            for line in source:
                target.write(line)
                if line == b'___SEMO_PAYLOAD___\r\n':
                    found = True
                    break
            if not found:
                raise ValueError('Authoritative CRLF payload marker not found')
            with cabinet.open('rb') as cab:
                while True:
                    chunk = cab.read(2850)  # exactly 3800 base64 characters, bounded RAM
                    if not chunk:
                        break
                    target.write(base64.b64encode(chunk) + b'\r\n')
        output.replace(bat)
    finally:
        output.unlink(missing_ok=True)
    sha = hashlib.sha256()
    with bat.open('rb') as result:
        for block in iter(lambda: result.read(1024 * 1024), b''):
            sha.update(block)
    print('AUTHORITATIVE_BAT_REPACK_PASS', sha.hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bat', type=Path)
    parser.add_argument('cab', type=Path)
    args = parser.parse_args()
    repack(args.bat, args.cab)
