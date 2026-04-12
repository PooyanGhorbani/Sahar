import base64
import io
import re
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = ROOT.joinpath('VERSION').read_text(encoding='utf-8').strip()


class ReleaseBundleConsistencyTests(unittest.TestCase):
    def test_top_level_version_strings_are_consistent(self):
        checks = {
            'README header': (ROOT / 'README.md').read_text(encoding='utf-8').splitlines()[0],
            'README badge': (ROOT / 'README.md').read_text(encoding='utf-8'),
            'install_master APP_VERSION': (ROOT / 'install_master.sh').read_text(encoding='utf-8'),
            'install_agent APP_VERSION': (ROOT / 'install_agent.sh').read_text(encoding='utf-8'),
            'single-file installer version': (ROOT / 'sahar-installer.sh').read_text(encoding='utf-8'),
        }
        self.assertIn(EXPECTED_VERSION, checks['README header'])
        self.assertIn(f'version-{EXPECTED_VERSION}', checks['README badge'])
        self.assertIn(f'APP_VERSION="{EXPECTED_VERSION}"', checks['install_master APP_VERSION'])
        self.assertIn(f'APP_VERSION="{EXPECTED_VERSION}"', checks['install_agent APP_VERSION'])
        self.assertIn(f'SAHAR_INSTALLER_VERSION="{EXPECTED_VERSION}"', checks['single-file installer version'])
        self.assertIn(f'Sahar single-file installer v{EXPECTED_VERSION}', checks['single-file installer version'])

    def test_single_file_installer_payload_matches_release_version(self):
        text = (ROOT / 'sahar-installer.sh').read_text(encoding='utf-8')
        match = re.search(r"read -r -d '' PAYLOAD_B64 <<'__SAHAR_PAYLOAD__' \|\| true\n(.*?)\n__SAHAR_PAYLOAD__", text, re.S)
        self.assertIsNotNone(match)
        payload = base64.b64decode(match.group(1).strip())
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as tf:
            version_text = tf.extractfile('./VERSION').read().decode('utf-8').strip()
            readme_text = tf.extractfile('./README.md').read().decode('utf-8')
            master_text = tf.extractfile('./install_master.sh').read().decode('utf-8')
            agent_text = tf.extractfile('./install_agent.sh').read().decode('utf-8')
        self.assertEqual(version_text, EXPECTED_VERSION)
        self.assertIn(f'# سحر {EXPECTED_VERSION}', readme_text)
        self.assertIn(f'APP_VERSION="{EXPECTED_VERSION}"', master_text)
        self.assertIn(f'APP_VERSION="{EXPECTED_VERSION}"', agent_text)

    def test_single_file_installer_payload_does_not_ship_python_cache_directories(self):
        text = (ROOT / 'sahar-installer.sh').read_text(encoding='utf-8')
        match = re.search(r"read -r -d '' PAYLOAD_B64 <<'__SAHAR_PAYLOAD__' \|\| true\n(.*?)\n__SAHAR_PAYLOAD__", text, re.S)
        self.assertIsNotNone(match)
        payload = base64.b64decode(match.group(1).strip())
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as tf:
            caches = [name for name in tf.getnames() if '__pycache__' in name or name.endswith('.pyc')]
        self.assertEqual(caches, [])


if __name__ == '__main__':
    unittest.main()
