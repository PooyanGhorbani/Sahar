import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'master_app'))
sys.path.insert(0, str(ROOT))

from master_app.utils import load_config, save_config


class UtilsAliasTests(unittest.TestCase):
    def test_cloudflare_alias_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'config.json')
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump({'cloudflare_argo_enabled': True, 'admin_chat_ids': '1,2'}, fh)
            cfg = load_config(path)
            self.assertTrue(cfg['cloudflare_tunnel_enabled'])
            self.assertEqual(cfg['admin_ids'], ['1', '2'])
            save_config(path, cfg)
            with open(path, 'r', encoding='utf-8') as fh:
                written = json.load(fh)
            self.assertTrue(written['cloudflare_argo_enabled'])

    def test_master_utils_expand_environment_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['SAHAR_MASTER_TMP'] = tmp
            actual_path = os.path.join(tmp, 'config.json')
            with open(actual_path, 'w', encoding='utf-8') as fh:
                json.dump({'cloudflare_tunnel_enabled': True, 'admin_chat_ids': '3'}, fh)
            cfg = load_config('$SAHAR_MASTER_TMP/config.json')
            self.assertTrue(cfg['cloudflare_argo_enabled'])
            self.assertEqual(cfg['admin_ids'], ['3'])
            cfg['bot_token'] = 'token'
            save_config('$SAHAR_MASTER_TMP/config.json', cfg)
            with open(actual_path, 'r', encoding='utf-8') as fh:
                written = json.load(fh)
            self.assertEqual(written['bot_token'], 'token')

    def test_cloudflare_alias_handles_string_false_without_flipping_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'config.json')
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump({'cloudflare_argo_enabled': 'false', 'admin_chat_ids': ''}, fh)
            cfg = load_config(path)
            self.assertFalse(cfg['cloudflare_tunnel_enabled'])
            self.assertFalse(cfg['cloudflare_argo_enabled'])

    def test_setup_logging_expands_environment_log_path(self):
        from master_app.utils import setup_logging
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['SAHAR_MASTER_LOG_TMP'] = tmp
            setup_logging('$SAHAR_MASTER_LOG_TMP/master.log')
            self.assertTrue(os.path.exists(os.path.join(tmp, 'master.log')))


if __name__ == '__main__':
    unittest.main()
