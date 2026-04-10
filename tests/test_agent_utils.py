import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent_app'))
sys.path.insert(0, str(ROOT))

from agent_app.utils import load_config, save_config, source_allowed


class AgentUtilsTests(unittest.TestCase):
    def test_load_and_save_expand_environment_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['SAHAR_AGENT_TMP'] = tmp
            config_path = os.path.join(tmp, 'agent.json')
            with open(config_path, 'w', encoding='utf-8') as fh:
                json.dump({'agent_name': 'edge-1'}, fh)
            cfg = load_config('$SAHAR_AGENT_TMP/agent.json')
            self.assertEqual(cfg['agent_name'], 'edge-1')
            cfg['agent_token'] = 'secret'
            save_config('$SAHAR_AGENT_TMP/agent.json', cfg)
            with open(config_path, 'r', encoding='utf-8') as fh:
                written = json.load(fh)
            self.assertEqual(written['agent_token'], 'secret')

    def test_source_allowed_is_fail_closed_but_accepts_matching_sources(self):
        self.assertFalse(source_allowed('127.0.0.1', []))
        self.assertFalse(source_allowed('not-an-ip', ['127.0.0.1/32']))
        self.assertTrue(source_allowed('127.0.0.1', ['127.0.0.1/32']))
        self.assertTrue(source_allowed('10.10.10.8', ['10.10.10.0/24']))
        self.assertFalse(source_allowed('10.10.11.8', ['10.10.10.0/24']))

    def test_any_allowed_source_marker_opens_intended_unrestricted_mode(self):
        from agent_app.utils import parse_allowed_sources
        self.assertEqual(parse_allowed_sources('ANY'), ['*'])
        self.assertEqual(parse_allowed_sources('*'), ['*'])
        self.assertTrue(source_allowed('203.0.113.9', ['*']))


if __name__ == '__main__':
    unittest.main()
