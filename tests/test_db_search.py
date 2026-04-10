import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'master_app'))
sys.path.insert(0, str(ROOT))

from master_app.db import Database


class DatabaseSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'test.db')
        self.db = Database(self.db_path)
        server_payload = {
            'name': 'ir1',
            'api_url': 'https://agent',
            'api_token': 'secret',
            'api_tls_fingerprint': 'fp',
            'public_host': '10.0.0.1',
            'host_mode': 'ip',
            'xray_port': 443,
            'transport_mode': 'ws',
            'ws_path': '/ws',
            'reality_server_name': '',
            'reality_public_key': '',
            'reality_short_id': '',
            'fingerprint': 'chrome',
            'reality_port': 8443,
            'enabled': True,
            'last_health_status': 'ok',
            'last_health_message': '',
            'last_health_at': '2025-01-01T00:00:00',
            'cf_zone_id': 'zone',
            'cf_record_id': 'record',
            'cf_record_type': 'CNAME',
            'cf_dns_name': 'ir1.example.com',
            'cf_tunnel_id': 'tun',
            'cf_tunnel_name': 'tunnel-ir1',
            'cf_tunnel_status': 'configured',
            'provisioning_state': 'healthy',
            'provisioning_message': 'ready',
            'created_at': '2025-01-01T00:00:00',
            'updated_at': '2025-01-01T00:00:00',
        }
        self.db.add_or_update_server(server_payload)
        server = self.db.get_server('ir1')
        self.db.add_user('alice', server['id'], 'uuid-1', 10, '2025-12-31', 'vip note', 'gold', '2025-01-01', '2025-01-01')

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_users_matches_server_name(self):
        rows = self.db.search_users('ir1')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['username'], 'alice')

    def test_search_servers_matches_dns_name(self):
        rows = self.db.search_servers('example.com')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'ir1')
        self.assertEqual(rows[0]['cf_tunnel_status'], 'configured')


if __name__ == '__main__':
    unittest.main()
