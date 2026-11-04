"""Offline regression coverage: version gates, auto setup, preservation and failure paths."""
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from idm_linux import media_dependencies as media
from idm_linux import distro, installer


class MediaDependenciesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'data'
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.env = patch.dict(os.environ, {'HOME': str(self.root), 'XDG_CONFIG_HOME': str(self.root / 'config')})
        self.env.start()
        self.addCleanup(self.env.stop)
        for name, value in [('get_data_dir', self.data), ('get_cache_dir', self.cache)]:
            p = patch.object(media, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        media._probe_runtime.cache_clear()
        media._probe_ffmpeg.cache_clear()
        self.runtime = media.JsRuntime('node', '/usr/bin/node', '22.23.4')

    def executable(self, name, text, code=0):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nprintf "%s\\n" ' + repr(text) + '\nexit ' + str(code) + '\n')
        path.chmod(0o755)
        return path

    def test_supported_version_boundaries(self):
        for name, minimum, old in [('node', 'v22.0.0', 'v20.99.0'), ('deno', 'deno 2.3.0', 'deno 2.2.99'), ('bun', '1.2.11', '1.2.10')]:
            for output, expected in [(minimum, True), (old, False), ('nonsense', False)]:
                with self.subTest(name=name, output=output):
                    path = self.executable('runtime', output)
                    media._probe_runtime.cache_clear()
                    self.assertEqual(bool(media._probe_runtime(name, str(path), 0, 0)), expected)

    def test_failing_executable_is_not_a_runtime(self):
        path = self.executable('node', 'v22.23.4', 1)
        self.assertIsNone(media._probe_runtime('node', str(path), 0, 0))

    def test_runtime_timeout_is_not_success(self):
        with patch.object(media.subprocess, 'run', side_effect=media.subprocess.TimeoutExpired('node', 3)):
            self.assertIsNone(media._probe_runtime('node', '/node', 0, 0))

    def test_old_node_does_not_hide_supported_bun(self):
        node = self.executable('node', 'v20.5.0')
        bun = self.executable('bun', '1.2.11')
        with patch.object(media.shutil, 'which', side_effect=lambda name: str({'node': node, 'bun': bun}[name]) if name in ('node', 'bun') else None):
            self.assertEqual(media.find_js_runtime().name, 'bun')

    def test_private_deno_detected_without_path_changes(self):
        path = self.data / 'bin' / 'deno'
        self.executable(str(path.relative_to(self.root)), 'deno 2.3.0')
        with patch.object(media.shutil, 'which', return_value=None):
            self.assertEqual(media.find_js_runtime().path, str(path))

    def test_ffmpeg_must_actually_start(self):
        for output, code, expected in [('ffmpeg version 8.0.1', 0, True), ('ffmpeg version broken', 1, False), ('not ffmpeg', 0, False)]:
            path = self.executable('ffmpeg', output, code)
            media._probe_ffmpeg.cache_clear()
            with patch.object(media.shutil, 'which', return_value=str(path)):
                self.assertEqual(bool(media.working_ffmpeg()), expected)

    def test_preserves_config_backup_and_is_idempotent(self):
        path = media.runtime_config_path()
        path.parent.mkdir(parents=True)
        original = '# my settings\n--format best\n--js-runtimes node\n'
        path.write_text(original)
        self.assertTrue(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        first = path.read_bytes()
        self.assertIn(original.strip(), first.decode())
        self.assertEqual(path.with_name(path.name + '.idm-linux.before').read_text(), original)
        self.assertTrue(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_replaces_only_owned_block(self):
        path = media.runtime_config_path()
        path.parent.mkdir(parents=True)
        old = '# retain\n' + media._START + '\n--js-runtimes node:/old\n' + media._END + '\n--format best\n'
        path.write_text(old)
        self.assertTrue(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        text = path.read_text()
        self.assertIn('# retain', text)
        self.assertIn('--format best', text)
        self.assertEqual(text.count(media._START), 1)
        self.assertNotIn('/old', text)

    def test_existing_higher_priority_config_selected(self):
        top = self.root / 'config' / 'yt-dlp.conf'
        lower = self.root / 'config' / 'yt-dlp' / 'config'
        lower.parent.mkdir(parents=True)
        top.write_text('# priority\n')
        lower.write_text('# lower\n')
        self.assertEqual(media.runtime_config_path(), top)
        self.assertTrue(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        self.assertEqual(lower.read_text(), '# lower\n')

    def test_legacy_home_config_is_not_shadowed_by_new_xdg_file(self):
        home = self.root / '.yt-dlp' / 'config'
        home.parent.mkdir()
        home.write_text('--format best\n')
        self.assertEqual(media.runtime_config_path(), home)

    def test_standalone_uses_private_portable_config(self):
        private = self.data / 'bin' / 'yt-dlp'
        self.executable(str(private.relative_to(self.root)), 'yt-dlp')
        self.assertEqual(media.runtime_config_path(), private.parent / 'yt-dlp.conf')
        self.assertTrue(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        self.assertFalse((self.root / 'config' / 'yt-dlp' / 'config').exists())

    def test_unterminated_managed_block_not_overwritten(self):
        path = media.runtime_config_path()
        path.parent.mkdir(parents=True)
        path.write_text(media._START + '\n# broken\n')
        before = path.read_bytes()
        self.assertFalse(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        self.assertEqual(path.read_bytes(), before)

    def test_config_write_permission_failure_preserves_original(self):
        path = media.runtime_config_path()
        path.parent.mkdir(parents=True)
        path.write_text('# keep\n')
        with patch.object(media.os, 'replace', side_effect=PermissionError('denied')):
            self.assertFalse(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        self.assertEqual(path.read_text(), '# keep\n')
        self.assertFalse(list(path.parent.glob('.idm-js-*')))

    def test_symlink_config_is_not_replaced(self):
        target = self.root / 'shared.conf'
        target.write_text('# preserve shared\n')
        path = media.runtime_config_path()
        path.parent.mkdir(parents=True)
        path.symlink_to(target)
        self.assertFalse(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_text(), '# preserve shared\n')

    def test_real_ytdlp_config_parser_keeps_user_settings_and_adds_runtime(self):
        try:
            from yt_dlp.options import parseOpts
        except ImportError:
            self.skipTest('Optional installed yt-dlp Python module unavailable')
        binary = self.data / 'bin' / 'yt-dlp'
        self.executable(str(binary.relative_to(self.root)), 'yt-dlp')
        user_config = self.root / 'config' / 'yt-dlp' / 'config'
        user_config.parent.mkdir(parents=True)
        user_config.write_text('--format best\n--js-runtimes node:/old-node\n')
        self.assertTrue(media.configure_ytdlp_runtime(self.runtime, log_fn=lambda _: None))
        with patch('yt_dlp.options.get_executable_path', return_value=str(binary.parent)), patch('yt_dlp.options.get_system_config_dirs', return_value=[]):
            _, options, _ = parseOpts(['--simulate'], ignore_config_files=False)
        self.assertEqual(options.format, 'best')
        self.assertEqual(options.js_runtimes[-1], 'node:/usr/bin/node')
        self.assertEqual(user_config.read_text(), '--format best\n--js-runtimes node:/old-node\n')

    def test_config_permission_failure_is_not_ready(self):
        with patch.object(media, 'find_js_runtime', return_value=self.runtime), patch.object(media, 'working_ffmpeg', return_value='/ffmpeg'), patch.object(distro, 'find_ytdlp', return_value='/yt-dlp'), patch.object(media, 'configure_ytdlp_runtime', return_value=False):
            result = media.ensure_media_dependencies(allow_install=False, log_fn=lambda _: None)
        self.assertFalse(result['ready'])
        self.assertIn('yt-dlp JS yapılandırması', result['missing'])

    def test_skip_packages_never_installs_or_downloads(self):
        with patch.object(media, 'find_js_runtime', return_value=None), patch.object(media, 'working_ffmpeg', return_value=None), patch.object(distro, 'find_ytdlp', return_value=None), patch.object(distro, '_run_priv') as privileged, patch.object(distro, 'install_standalone_ytdlp') as download, patch.object(media, 'install_private_deno') as fallback:
            result = media.ensure_media_dependencies(allow_install=False, log_fn=lambda _: None)
        self.assertFalse(result['ready'])
        privileged.assert_not_called()
        download.assert_not_called()
        fallback.assert_not_called()

    def test_missing_packages_auto_install_then_verify(self):
        with patch.object(media, 'find_js_runtime', side_effect=[None, self.runtime]), patch.object(media, 'working_ffmpeg', side_effect=[None, '/ffmpeg']), patch.object(distro, 'find_ytdlp', return_value='/yt-dlp'), patch.object(distro, 'detect_pkg_manager', return_value='apt'), patch.object(distro, '_run_priv', return_value=0) as privileged, patch.object(media, 'configure_ytdlp_runtime', return_value=True):
            result = media.ensure_media_dependencies(log_fn=lambda _: None)
        self.assertTrue(result['ready'])
        self.assertEqual(privileged.call_args_list[0].args[0], ['apt-get', 'update'])
        self.assertEqual(privileged.call_args_list[1].args[0], ['apt-get', 'install', '-y', 'ffmpeg', 'nodejs'])

    def test_old_distro_runtime_uses_private_fallback(self):
        with patch.object(media, 'find_js_runtime', return_value=None), patch.object(media, 'working_ffmpeg', return_value='/ffmpeg'), patch.object(distro, 'find_ytdlp', return_value='/yt-dlp'), patch.object(distro, 'detect_pkg_manager', return_value='apt'), patch.object(distro, '_run_priv', return_value=0), patch.object(media, 'install_private_deno', return_value=self.runtime) as fallback, patch.object(media, 'configure_ytdlp_runtime', return_value=True):
            self.assertTrue(media.ensure_media_dependencies(log_fn=lambda _: None)['ready'])
        fallback.assert_called_once()

    def test_permission_or_package_failure_cannot_report_success(self):
        with patch.object(media, 'find_js_runtime', return_value=None), patch.object(media, 'working_ffmpeg', return_value=None), patch.object(distro, 'find_ytdlp', return_value='/yt-dlp'), patch.object(distro, 'detect_pkg_manager', return_value='apt'), patch.object(distro, '_run_priv', return_value=1), patch.object(media, 'install_private_deno', return_value=None):
            result = media.ensure_media_dependencies(log_fn=lambda _: None)
        self.assertFalse(result['ready'])
        self.assertIn('FFmpeg', result['missing'])

    def deno_fixture(self, digest=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('deno', '#!/bin/sh\necho "deno 2.3.0"\n')
        blob = stream.getvalue()
        release = {'assets': [{'name': 'deno-x86_64-unknown-linux-gnu.zip', 'digest': digest or 'sha256:' + hashlib.sha256(blob).hexdigest(), 'browser_download_url': 'https://github.com/denoland/deno/releases/download/v2.3.0/deno-x86_64-unknown-linux-gnu.zip'}]}
        return [io.BytesIO(json.dumps(release).encode()), io.BytesIO(blob)]

    def test_private_fallback_checksum_and_version_verified(self):
        with patch.object(media.platform, 'machine', return_value='x86_64'), patch.object(media.platform, 'system', return_value='Linux'), patch.object(media.platform, 'libc_ver', return_value=('glibc', '2.39')), patch.object(media.urllib.request, 'urlopen', side_effect=self.deno_fixture()), patch.object(media.shutil, 'which', return_value=None):
            runtime = media.install_private_deno(log_fn=lambda _: None)
        self.assertEqual(runtime.name, 'deno')
        self.assertEqual(runtime.version, '2.3.0')
        self.assertTrue((self.data / 'bin' / 'deno').is_file())
        self.assertFalse(list(self.cache.iterdir()))

    def test_bad_download_digest_never_installs(self):
        with patch.object(media.platform, 'machine', return_value='x86_64'), patch.object(media.platform, 'system', return_value='Linux'), patch.object(media.platform, 'libc_ver', return_value=('glibc', '2.39')), patch.object(media.urllib.request, 'urlopen', side_effect=self.deno_fixture('sha256:' + '0' * 64)):
            self.assertIsNone(media.install_private_deno(log_fn=lambda _: None))
        self.assertFalse((self.data / 'bin' / 'deno').exists())
        self.assertFalse(list(self.cache.iterdir()))

    def test_unsupported_architecture_does_not_download(self):
        with patch.object(media.platform, 'machine', return_value='riscv64'), patch.object(media.urllib.request, 'urlopen') as download:
            self.assertIsNone(media.install_private_deno(log_fn=lambda _: None))
        download.assert_not_called()

    def test_pipeline_stops_before_idm_download_if_media_not_ready(self):
        cfg = SimpleNamespace(ws_port=17801, http_port=17802, download_dir=str(self.root / 'downloads'), save=Mock())
        info = SimpleNamespace(distro_name='Test', pkg_manager='apt', init_system='xdg', display_server='x11')
        with patch.object(installer.IdmLinuxConfig, 'load', return_value=cfg), patch.object(installer, 'detect_system', return_value=info), patch.object(installer, 'install_system_dependencies', return_value=info), patch.object(installer, 'ensure_media_dependencies', return_value={'ready': False, 'missing': ['FFmpeg']}), patch.object(installer, 'resolve_latest_official_idm_release') as resolve:
            with self.assertRaisesRegex(RuntimeError, 'Video bileşenleri'):
                installer.execute_install_pipeline(self.root, self.root / 'prefix', existing_items=[], log_fn=lambda _: None)
        resolve.assert_not_called()

    def test_pipeline_explicit_skip_is_respected(self):
        cfg = SimpleNamespace(ws_port=17801, http_port=17802, download_dir=str(self.root / 'downloads'), save=Mock(), idm_installer_url='https://example.test')
        info = SimpleNamespace(distro_name='Test', pkg_manager='apt', init_system='xdg', display_server='x11')
        with patch.object(installer.IdmLinuxConfig, 'load', return_value=cfg), patch.object(installer, 'detect_system', return_value=info), patch.object(installer, 'install_system_dependencies') as dependencies, patch.object(installer, 'ensure_media_dependencies', return_value={'ready': False, 'missing': ['FFmpeg']}) as check, patch.object(installer, 'resolve_latest_official_idm_release', side_effect=RuntimeError('reached next step')):
            with self.assertRaisesRegex(RuntimeError, 'reached next step'):
                installer.execute_install_pipeline(self.root, self.root / 'prefix', existing_items=[], skip_system_pkgs=True, log_fn=lambda _: None)
        dependencies.assert_not_called()
        self.assertFalse(check.call_args.kwargs['allow_install'])

    def test_all_language_summaries_accept_js(self):
        for path in (Path(media.__file__).parent / 'language').glob('*.txt'):
            line = next(line for line in path.read_text().splitlines() if line.startswith('inst.sys_summary ='))
            self.assertIn('JS=22', line.split('=', 1)[1].format(distro='D', pm='P', wine='W', ytdlp='Y', ffmpeg='F', aria2='A', js='22'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
