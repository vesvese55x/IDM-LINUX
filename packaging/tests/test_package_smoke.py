import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('package_smoke', Path(__file__).resolve().parents[1]/'linux/test_packages.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class PackageSmokeTests(unittest.TestCase):
    def test_four_unchanged_version_names(self):
        self.assertEqual(set(smoke.NAMES), {'deb','rpm','zst','appimage'})
        self.assertTrue(all('1.0.0' in name for name in smoke.NAMES.values()))

    def test_payload_sha_covers_runtime_and_rejects_modified_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'checkout'
            payload = Path(directory)/'package'
            for i in range(55):
                relative = Path('src/idm_linux')/('fixture'+str(i)+'.py')
                for base in [root, payload]:
                    (base/relative).parent.mkdir(parents=True, exist_ok=True)
                    (base/relative).write_text(str(i))
            relative = Path('src/idm_linux/extension/chromium/background.js')
            for base in [root, payload]:
                (base/relative).parent.mkdir(parents=True, exist_ok=True)
                (base/relative).write_text('same')
            with patch.object(smoke, 'ROOT', root):
                self.assertEqual(smoke.verify_payload(payload), 56)
                (payload/relative).write_text('stale extension')
                with self.assertRaisesRegex(AssertionError, 'background.js'):
                    smoke.verify_payload(payload)

    def test_actual_mixed_case_translated_window_title(self):
        self.assertTrue(smoke.gui_ready('IDM Linux Kontrol Merkezi — v1.0.0'))
        self.assertTrue(smoke.gui_ready('IDM Linux Control Center — v1.0.0'))
        self.assertFalse(smoke.gui_ready('IDM Linux v2.0.0'))
        self.assertFalse(smoke.gui_ready('unrelated window v1.0.0'))

    def test_empty_payload_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(smoke, 'ROOT', Path(directory)):
                with self.assertRaisesRegex(AssertionError, 'small runtime'):
                    smoke.verify_payload(Path(directory))


if __name__ == '__main__':
    unittest.main()
