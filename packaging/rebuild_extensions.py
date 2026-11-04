#!/usr/bin/env python3
"""Rebuild/check companion archives without changing versions or extension IDs."""
import argparse
import io
import json
import struct
import sys
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from idm_linux.crx_builder import build_chromium_zip_package, build_crx3_package, verify_crx3_package
from idm_linux.config import COMPANION_CHROME_EXT_ID
EXT = ROOT / 'src/idm_linux/extension'


def verify_archive(data, source):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expected = {p.relative_to(source).as_posix(): p for p in source.rglob('*') if p.is_file()}
        if set(archive.namelist()) != set(expected):
            raise ValueError('Archive file inventory differs from source')
        for name, path in expected.items():
            if archive.read(name) != path.read_bytes():
                raise ValueError('Stale packaged extension file: ' + name)
        if json.loads(archive.read('manifest.json'))['version'] != '1.0.0':
            raise ValueError('Version must remain 1.0.0')


def main(check=False):
    chromium, firefox = EXT / 'chromium', EXT / 'firefox'
    chrome_zip = EXT / 'idm-linux-companion-chromium.zip'
    chrome_crx = EXT / 'idm-linux-companion-chromium.crx'
    gecko_xpi = EXT / 'idm-linux-companion-firefox.xpi'
    if not check:
        build_chromium_zip_package(chromium, chrome_zip)
        _, extension_id = build_crx3_package(chromium, chrome_crx)
        assert extension_id == COMPANION_CHROME_EXT_ID
        with zipfile.ZipFile(gecko_xpi, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(firefox.rglob('*')):
                if path.is_file(): archive.write(path, path.relative_to(firefox).as_posix())
    ok, error = verify_crx3_package(chrome_crx)
    if not ok: raise ValueError(error)
    crx = chrome_crx.read_bytes()
    offset = 12 + struct.unpack_from('<I', crx, 8)[0]
    verify_archive(crx[offset:], chromium)
    verify_archive(chrome_zip.read_bytes(), chromium)
    verify_archive(gecko_xpi.read_bytes(), firefox)
    print('EXTENSION_ARCHIVES_SOURCE_EQUAL_CRX_SIGNATURE_ID_VERSION_PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    main(parser.parse_args().check)
