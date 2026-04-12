import unittest

from master_app.panel_logic import build_dashboard_text, merge_server_runtime_update


class PanelLogicTests(unittest.TestCase):
    def test_merge_server_runtime_update_preserves_cloudflare_fields(self):
        server = {
            'name': 'ir1',
            'api_url': 'https://agent',
            'api_token': 'secret',
            'api_tls_fingerprint': 'oldfp',
            'public_host': '1.1.1.1',
            'host_mode': 'ip',
            'xray_port': 443,
            'transport_mode': 'ws',
            'ws_path': '/ws',
            'reality_server_name': 'cdn.example.com',
            'reality_public_key': 'pub',
            'reality_short_id': 'abcd',
            'fingerprint': 'chrome',
            'reality_port': 8443,
            'enabled': True,
            'cpu_percent': 11,
            'memory_percent': 22,
            'disk_percent': 33,
            'load_1m': 0.5,
            'user_count': 10,
            'xray_active': True,
            'last_sync_at': '2025-01-01T00:00:00',
            'cf_zone_id': 'zone1',
            'cf_record_id': 'rec1',
            'cf_record_type': 'CNAME',
            'cf_dns_name': 'ir1.example.com',
            'cf_tunnel_id': 'tun1',
            'cf_tunnel_name': 'tunnel-ir1',
            'cf_tunnel_status': 'configured',
            'provisioning_state': 'healthy',
            'provisioning_message': 'ok',
            'created_at': '2025-01-01T00:00:00',
        }
        health = {
            'public_host': '2.2.2.2',
            'simple_port': 2053,
            'transport_mode': 'tcp',
            'tls_fingerprint': 'newfp',
            'cpu_percent': 70,
            'xray_active': False,
        }
        merged = merge_server_runtime_update(server, health, '2025-02-01T00:00:00')
        self.assertEqual(merged['cf_record_type'], 'CNAME')
        self.assertEqual(merged['cf_tunnel_id'], 'tun1')
        self.assertEqual(merged['cf_tunnel_status'], 'configured')
        self.assertEqual(merged['api_tls_fingerprint'], 'newfp')
        self.assertEqual(merged['public_host'], '2.2.2.2')
        self.assertEqual(merged['xray_port'], 2053)
        self.assertFalse(merged['xray_active'])

    def test_dashboard_text_contains_operational_summary(self):
        text = build_dashboard_text(
            users=[{'is_active': True}, {'is_active': False}],
            servers=[{'enabled': True, 'last_health_status': 'ok'}, {'enabled': True, 'last_health_status': 'warn'}],
            version='0.1.74',
            bot_state='active',
            scheduler_state='active',
            subscription_state='inactive',
            local_agent_state='disabled',
            expired_count=3,
            quota_count=4,
            error_count=2,
        )
        self.assertIn('کاربران: 2 | فعال: 1', text)
        self.assertIn('سرورها: 2 | سالم: 1 | مشکل‌دار: 1', text)
        self.assertIn('کاربران منقضی فعال: 3', text)
        self.assertIn('خطاهای اخیر: 2', text)
        self.assertIn('🤖 بات: 🟢 فعال', text)
        self.assertIn('📌 جمع‌بندی:', text)


if __name__ == '__main__':
    unittest.main()
