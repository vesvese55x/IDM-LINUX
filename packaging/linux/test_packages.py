#!/usr/bin/env python3
"""Execute real package entry points and observe their GUI on an isolated X11 screen.

Default: install DEB on the disposable Ubuntu runner, extract RPM/ALPM payloads,
and execute AppImage without FUSE. --installed-kind verifies a package installed
by the native Fedora/Arch package manager in a separate disposable container.
No Wine/IDM downloads are started. These are startup, not end-to-end IDM tests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
NAMES = {
    'deb': 'idm-linux_1.0.0_all.deb',
    'rpm': 'idm-linux-1.0.0-1.noarch.rpm',
    'zst': 'idm-linux-1.0.0-1-any.pkg.tar.zst',
    'appimage': 'IDM-LINUX-1.0.0-x86_64.AppImage',
}


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, timeout=180, **kwargs)


def verify_payload(payload):
    checked = 0
    for source in (ROOT / 'src/idm_linux').rglob('*'):
        relative = source.relative_to(ROOT / 'src/idm_linux')
        if not source.is_file() or any(p in {'tests', 'docs', 'packaging', '__pycache__'} for p in relative.parts) or source.suffix == '.pyc':
            continue
        target = payload / 'src/idm_linux' / relative
        if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
            raise AssertionError('Package payload differs from checked-out source: ' + str(relative))
        checked += 1
    if checked < 50:
        raise AssertionError('Implausibly small runtime payload')
    return checked


def startup(kind, payload, command, output, mode):
    from PIL import ImageGrab
    checked = verify_payload(payload)
    with tempfile.TemporaryDirectory(prefix='idm-package-home-') as home:
        env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=home+'/config',
                   XDG_DATA_HOME=home+'/data', XDG_CACHE_HOME=home+'/cache',
                   WINEPREFIX=home+'/.wine', APPIMAGE_EXTRACT_AND_RUN='1')
        # Never import a developer checkout accidentally.
        env.pop('PYTHONPATH', None)
        status = run(*command, 'status', env=env, capture_output=True, text=True)
        (output / (kind+'-status.log')).write_text(status.stdout+status.stderr)
        if 'v1.0.0' not in status.stdout or 'Durum Raporu' not in status.stdout:
            raise AssertionError('Actual package CLI did not produce its status report')
        captures = []
        for page, args in [('installer', []), ('overview', ['panel'])]:
            log = output / (kind+'-'+page+'.log')
            with log.open('w') as stream:
                process = subprocess.Popen([str(x) for x in command] + args, env=env,
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           start_new_session=True)
                try:
                    deadline = time.monotonic()+30
                    tree = ''
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise AssertionError('Package GUI exited early: '+log.read_text()[-2000:])
                        tree = run('xwininfo', '-root', '-tree', env=env, capture_output=True, text=True).stdout
                        if 'IDM LINUX' in tree and '1.0.0' in tree:
                            time.sleep(3)
                            break
                        time.sleep(.4)
                    else:
                        raise AssertionError('Package did not show its production GUI: '+tree[-1500:])
                    image = ImageGrab.grab(xdisplay=env['DISPLAY'])
                    if len(image.resize((100,100)).getcolors(10001) or []) < 15:
                        raise AssertionError('Blank GUI screen')
                    screenshot = output / (kind+'-'+page+'.png')
                    image.save(screenshot)
                    captures.append({'page':page, 'screenshot':screenshot.name,
                                     'sha256':hashlib.sha256(screenshot.read_bytes()).hexdigest()})
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
            if 'Traceback (most recent call last)' in log.read_text():
                raise AssertionError('GUI exception in '+str(log))
        return {'kind':kind, 'mode':mode, 'runtime_files_sha_equal':checked,
                'cli_status':'PASS', 'actual_package_entrypoint':list(map(str,command)),
                'gui_pages':captures, 'native_idman_download_test':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-kind', choices=['rpm','zst'])
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/package-smoke')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    # Persist a partial manifest even if a later platform fails.
    try:
        if args.installed_kind:
            results.append(startup(args.installed_kind, Path('/opt/idm-linux'),
                                   ['/usr/bin/idm-linux'], output, 'native-package-manager-install'))
        else:
            dist = ROOT/'dist'
            for kind, name in NAMES.items():
                with tempfile.TemporaryDirectory(prefix='idm-package-'+kind+'-') as temporary:
                    stage = Path(temporary)
                    package = dist/name
                    if kind == 'deb':
                        run('sudo', 'dpkg', '-i', package)
                        payload = Path('/opt/idm-linux')
                        command = ['/usr/bin/idm-linux']
                        mode = 'native-dpkg-install'
                    elif kind == 'rpm':
                        producer = subprocess.Popen(['rpm2cpio', str(package)], stdout=subprocess.PIPE)
                        try:
                            run('cpio', '-idm', '--quiet', cwd=stage, stdin=producer.stdout)
                        finally:
                            producer.stdout.close()
                            code = producer.wait(timeout=30)
                        if code:
                            raise RuntimeError('rpm2cpio failed')
                        payload = stage/'opt/idm-linux'
                        command = [payload/'src/idm_linux/bin/idm-linux']
                        mode = 'extracted-payload; separate-native-Fedora-job-required'
                    elif kind == 'zst':
                        run('tar', '--zstd', '-xf', package, '-C', stage)
                        payload = stage/'opt/idm-linux'
                        command = [payload/'src/idm_linux/bin/idm-linux']
                        mode = 'extracted-payload; separate-native-Arch-job-required'
                    else:
                        package.chmod(0o755)
                        run(package, '--appimage-extract', cwd=stage, stdout=subprocess.DEVNULL)
                        payload = stage/'squashfs-root/usr/share/idm-linux'
                        command = [package]
                        mode = 'actual-AppImage-extract-and-run-no-FUSE'
                    results.append(startup(kind, payload, command, output, mode))
                    print('ACTUAL_PACKAGE_CLI_AND_GUI_PASS', kind, flush=True)
    finally:
        (output/'package-startup-manifest.json').write_text(json.dumps({
            'source_commit':os.environ.get('GITHUB_SHA'), 'version':'1.0.0',
            'native_idman_download_test':False, 'results':results,
            'expected_results':1 if args.installed_kind else 4}, indent=2))


if __name__ == '__main__':
    main()
