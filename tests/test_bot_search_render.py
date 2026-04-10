import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'master_app'))
sys.path.insert(0, str(ROOT))


def install_telegram_stubs():
    telegram = types.ModuleType('telegram')

    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    class Update:
        ALL_TYPES = []

    telegram.InlineKeyboardButton = InlineKeyboardButton
    telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
    telegram.Update = Update

    constants = types.ModuleType('telegram.constants')
    constants.ParseMode = types.SimpleNamespace(HTML='HTML')

    error_mod = types.ModuleType('telegram.error')
    class BadRequest(Exception):
        pass
    error_mod.BadRequest = BadRequest

    ext = types.ModuleType('telegram.ext')
    class _DummyBuilder:
        def token(self, _token):
            return self
        def build(self):
            return types.SimpleNamespace(add_handler=lambda *a, **k: None, add_error_handler=lambda *a, **k: None, run_polling=lambda **k: None)
    class Application:
        @staticmethod
        def builder():
            return _DummyBuilder()
    class CallbackQueryHandler:
        def __init__(self, *args, **kwargs):
            pass
    class CommandHandler:
        def __init__(self, *args, **kwargs):
            pass
    class MessageHandler:
        def __init__(self, *args, **kwargs):
            pass
    class ContextTypes:
        DEFAULT_TYPE = object
    class _Filters:
        TEXT = 1
        COMMAND = 2
    ext.Application = Application
    ext.CallbackQueryHandler = CallbackQueryHandler
    ext.CommandHandler = CommandHandler
    ext.ContextTypes = ContextTypes
    ext.MessageHandler = MessageHandler
    ext.filters = _Filters()

    sys.modules['telegram'] = telegram
    sys.modules['telegram.constants'] = constants
    sys.modules['telegram.error'] = error_mod
    sys.modules['telegram.ext'] = ext

    paramiko = types.ModuleType('paramiko')
    class SSHClient:
        def __init__(self, *args, **kwargs):
            pass
    class AutoAddPolicy:
        def __init__(self, *args, **kwargs):
            pass
    paramiko.SSHClient = SSHClient
    paramiko.AutoAddPolicy = AutoAddPolicy
    sys.modules['paramiko'] = paramiko


class BotSearchRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        config_path = root / 'config.json'
        (root / 'backups').mkdir(parents=True, exist_ok=True)
        (root / 'qr').mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({
            'bot_token': '',
            'admin_chat_ids': '',
            'database_path': str(root / 'master.db'),
            'log_path': str(root / 'master.log'),
            'qr_dir': str(root / 'qr'),
            'backup_dir': str(root / 'backups'),
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
            'local_node_enabled': False,
            'local_server_name': 'local',
            'local_agent_api_url': '',
            'local_agent_api_token': '',
        }), encoding='utf-8')
        os.environ['SAHAR_CONFIG'] = str(config_path)
        install_telegram_stubs()
        sys.modules.pop('bot', None)
        self.bot = importlib.import_module('bot')

    def tearDown(self):
        sys.modules.pop('bot', None)
        os.environ.pop('SAHAR_CONFIG', None)
        self.tmp.cleanup()

    def _button_labels(self, markup):
        return [btn.text for row in markup.inline_keyboard for btn in row]

    def test_search_users_view_can_hide_empty_server_block(self):
        text, markup = self.bot.build_combined_search_result(
            'alice',
            users=[{'username': 'alice', 'server_name': 'ir1', 'plan': 'gold', 'is_active': True}],
            servers=[],
            include_servers=False,
        )
        self.assertIn('👥 کاربران: 1', text)
        self.assertNotIn('🌐 سرورها:', text)
        labels = self._button_labels(markup)
        self.assertIn('👤 alice', labels)
        self.assertIn('🔁 جستجوی کاربر', labels)
        self.assertIn('🏠 خانه', labels)

    def test_format_user_brief_escapes_html_sensitive_fields(self):
        rendered = self.bot.format_user_brief({
            'username': '<admin>',
            'server_name': 'edge&1',
            'used_gb': 3,
            'traffic_gb': 10,
            'expire_date': '2026-01-01',
            'is_active': True,
        })
        self.assertIn('&lt;admin&gt;', rendered)
        self.assertIn('edge&amp;1', rendered)
        self.assertNotIn('<admin>', rendered)

    def test_user_text_escapes_username_server_and_notes(self):
        self.bot.subscription_url_for_user = lambda username: 'https://sub.example/u?x=1&y=2'
        self.bot.subscription_raw_url_for_user = lambda username: 'https://sub.example/raw?x=1&y=2'
        self.bot.build_vless_link = lambda user: 'vless://demo?path=/ws&host=edge.example.com'
        text = self.bot.user_text({
            'username': '<b>Alice</b>',
            'server_name': 'edge<1>',
            'uuid': 'abc123',
            'traffic_gb': 50,
            'used_gb': 10,
            'expire_date': '2026-01-01',
            'credit_balance': 0,
            'plan': 'gold',
            'notes': 'needs <review> & retry',
            'is_active': True,
        })
        self.assertIn('&lt;b&gt;Alice&lt;/b&gt;', text)
        self.assertIn('edge&lt;1&gt;', text)
        self.assertIn('needs &lt;review&gt; &amp; retry', text)
        self.assertIn('https://sub.example/u?x=1&amp;y=2', text)

    def test_server_text_escapes_untrusted_fields(self):
        text = self.bot.server_text({
            'name': 'edge<script>',
            'api_url': 'https://agent.local?a=1&b=2',
            'public_host': 'node<1>',
            'xray_port': 443,
            'transport_mode': 'ws',
            'ws_path': '/ws',
            'last_health_status': 'ok',
            'last_health_message': 'bad <tag>',
            'last_health_at': '2026-01-01T00:00:00',
            'cpu_percent': 10,
            'memory_percent': 20,
            'disk_percent': 30,
            'load_1m': 0.5,
            'user_count': 5,
            'last_sync_at': '2026-01-01T00:00:00',
            'cf_dns_name': 'edge.example.com',
            'cf_tunnel_name': 'tun<1>',
            'cf_tunnel_status': 'configured & warm',
            'provisioning_state': 'healthy',
            'provisioning_message': 'all <good>',
            'enabled': True,
        })
        self.assertIn('edge&lt;script&gt;', text)
        self.assertIn('node&lt;1&gt;', text)
        self.assertIn('bad &lt;tag&gt;', text)
        self.assertIn('tun&lt;1&gt; | configured &amp; warm', text)
        self.assertIn('all &lt;good&gt;', text)

    def test_combined_search_result_reports_truncation_and_retry_action(self):
        users = [{'username': f'user{i}', 'server_name': 'ir1', 'used_gb': i, 'traffic_gb': 100, 'expire_date': '2026-01-01', 'is_active': True} for i in range(10)]
        servers = [{'id': i + 1, 'name': f'server{i}', 'last_health_status': 'ok', 'cf_dns_name': f'server{i}.example.com'} for i in range(7)]
        text, markup = self.bot.build_combined_search_result('edge', users, servers)
        self.assertIn('📦 نتیجه‌ها: 17', text)
        self.assertIn('… 2 کاربر دیگر هم پیدا شد', text)
        self.assertIn('… 1 سرور دیگر هم پیدا شد', text)
        labels = self._button_labels(markup)
        self.assertIn('🔁 جستجوی دوباره', labels)
        self.assertEqual(labels.count('🏠 خانه'), 1)

    def test_combined_search_result_empty_state_has_guidance(self):
        text, markup = self.bot.build_combined_search_result('zzz', [], [])
        self.assertIn('موردی پیدا نشد.', text)
        self.assertIn('نام کاربر، نام سرور، دامنه، پلن یا بخشی از یادداشت را امتحان کن.', text)
        labels = self._button_labels(markup)
        self.assertIn('🔁 جستجوی دوباره', labels)


    def test_list_text_escapes_dynamic_title(self):
        text = self.bot.list_text('سرور <main>&1', ['ok'])
        self.assertIn('<b>سرور &lt;main&gt;&amp;1</b>', text)
        self.assertNotIn('<b>سرور <main>&1</b>', text)

    def test_health_report_text_escapes_server_name_and_status(self):
        class FakeDB:
            def list_servers(self_inner):
                return [{
                    'name': 'edge<script>',
                    'enabled': True,
                    'last_health_status': 'down&bad',
                    'provisioning_state': 'sync<wait>',
                    'xray_active': False,
                    'cpu_percent': 10,
                    'memory_percent': 20,
                    'disk_percent': 30,
                    'user_count': 2,
                }]
        old_db = self.bot.DB
        self.bot.DB = FakeDB()
        try:
            text = self.bot.health_report_text()
        finally:
            self.bot.DB = old_db
        self.assertIn('edge&lt;script&gt;', text)
        self.assertIn('down&amp;bad', text)
        self.assertIn('sync&lt;wait&gt;', text)

    def test_xray_status_text_escapes_dynamic_fields(self):
        class FakeDB:
            def get_server(self_inner, _name):
                return {
                    'name': 'edge<script>',
                    'enabled': True,
                    'last_health_status': 'ok&warm',
                    'public_host': 'node<1>',
                    'xray_port': 443,
                    'reality_port': 8443,
                    'transport_mode': 'ws<script>',
                }
        class FakeClient:
            def health(self_inner):
                return {'data': {'xray_active': True, 'cpu_percent': 5, 'memory_percent': 6, 'disk_percent': 7}}
            def get(self_inner, path):
                self.assertEqual(path, '/config/summary')
                return {'data': {'public_host': 'cfg<host>', 'simple_port': '80&81', 'reality_port': '443<tls>', 'transport_mode': 'grpc&ws'}}
        old_db = self.bot.DB
        old_client = self.bot.server_client
        self.bot.DB = FakeDB()
        self.bot.server_client = lambda _server: FakeClient()
        try:
            text = self.bot.xray_status_text('edge<script>')
        finally:
            self.bot.DB = old_db
            self.bot.server_client = old_client
        self.assertIn('edge&lt;script&gt;', text)
        self.assertIn('ok&amp;warm', text)
        self.assertIn('cfg&lt;host&gt;', text)
        self.assertIn('80&amp;81', text)
        self.assertIn('443&lt;tls&gt;', text)
        self.assertIn('grpc&amp;ws', text)
    def test_local_server_detection_accepts_https_loopback(self):
        self.bot.config['local_server_name'] = 'local'
        self.assertTrue(self.bot._is_local_server({'name': 'edge', 'api_url': 'https://127.0.0.1:8787'}))
        self.assertTrue(self.bot._is_local_server({'name': 'edge', 'api_url': 'https://localhost:8787'}))
        self.assertFalse(self.bot._is_local_server({'name': 'edge', 'api_url': 'https://198.51.100.10:8787'}))


if __name__ == '__main__':
    unittest.main()
