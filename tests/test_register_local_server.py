import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'master_app'))
sys.path.insert(0, str(ROOT))


class RegisterLocalServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / 'config.json'
        self.local_config_path = self.root / 'local-agent-config.json'
        self.db_path = self.root / 'master.db'
        self.log_path = self.root / 'master.log'
        self.backup_dir = self.root / 'backups'
        self.qr_dir = self.root / 'qr'
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.qr_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps({
            'bot_token': '',
            'admin_chat_ids': '',
            'database_path': str(self.db_path),
            'log_path': str(self.log_path),
            'qr_dir': str(self.qr_dir),
            'backup_dir': str(self.backup_dir),
            'scheduler_interval_seconds': 300,
            'agent_timeout_seconds': 5,
            'warn_days_left': 3,
            'warn_usage_percent': 80,
            'backup_interval_hours': 24,
            'backup_retention': 5,
            'package_version': '0.1.70',
            'cloudflare_enabled': False,
            'cloudflare_domain_name': '',
            'cloudflare_zone_name': '',
            'cloudflare_base_subdomain': '',
            'cloudflare_token_encryption_key': '',
            'cloudflare_dns_proxied': False,
            'cloudflare_tunnel_enabled': False,
            'cloudflare_argo_enabled': False,
            'cloudflare_auto_sync_enabled': False,
            'cloudflare_auto_sync_interval_minutes': 30,
            'notify_on_server_status_change': True,
            'subscription_base_url': '',
            'subscription_bind_host': '127.0.0.1',
            'subscription_bind_port': 8080,
            'local_node_enabled': True,
            'local_server_name': 'local',
            'local_agent_api_url': 'http://127.0.0.1:8787',
            'local_agent_api_token': 'token-123',
            'local_agent_api_tls_fingerprint': '',
        }), encoding='utf-8')
        self.local_config_path.write_text(json.dumps({
            'agent_name': 'local',
            'public_host': '127.0.0.1',
            'host_mode': 'ip',
            'transport_mode': 'ws',
            'ws_path': '/ws-local',
            'xray_port': 443,
            'simple_port': 443,
            'reality_port': 8443,
            'reality_server_name': 'www.cloudflare.com',
            'fingerprint': 'chrome',
        }), encoding='utf-8')
        os.environ['SAHAR_CONFIG'] = str(self.config_path)
        sys.modules.pop('register_local_server', None)
        self.module = importlib.import_module('register_local_server')

    def tearDown(self):
        sys.modules.pop('register_local_server', None)
        os.environ.pop('SAHAR_CONFIG', None)
        self.tmp.cleanup()

    def test_register_uses_fallback_metadata_when_agent_is_unavailable(self):
        def fail_fetch(_client):
            raise self.module.AgentError('health endpoint unavailable')

        self.module._fetch_local_agent_metadata = fail_fetch
        self.module.register()
        server = self.module.DB.get_server('local')
        self.assertIsNotNone(server)
        self.assertEqual(server['api_url'], 'http://127.0.0.1:8787')
        self.assertEqual(server['ws_path'], '/ws-local')
        self.assertEqual(server['xray_port'], 443)
        self.assertEqual(server['last_health_status'], 'warn')
        self.assertIn('fallback', server['provisioning_message'])


if __name__ == '__main__':
    unittest.main()
