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


class CloudflareWorkflowTests(unittest.TestCase):
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
            'package_version': '0.1.72',
            'cloudflare_enabled': True,
            'cloudflare_domain_name': 'example.com',
            'cloudflare_zone_name': 'example.com',
            'cloudflare_base_subdomain': 'vpn',
            'cloudflare_token_encryption_key': 'MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=',
            'cloudflare_dns_proxied': True,
            'cloudflare_tunnel_enabled': True,
            'cloudflare_argo_enabled': True,
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

    def test_cloudflare_test_text_renders_connection_details(self):
        class FakeCF:
            tunnel_enabled = True
            def test_connection(self_inner):
                return {
                    'domain': 'example.com',
                    'zone_id': 'zone-123',
                    'account_id': 'acct-456',
                    'token': 'configured',
                }
        old_cf = self.bot.CLOUDFLARE
        self.bot.CLOUDFLARE = FakeCF()
        try:
            text = self.bot.cloudflare_test_text()
        finally:
            self.bot.CLOUDFLARE = old_cf
        self.assertIn('zone-123', text)
        self.assertIn('acct-456', text)
        self.assertIn('example.com', text)
        self.assertIn('configured', text)

    def test_sync_cloudflare_for_remote_server_without_tunnel_marks_pending(self):
        calls = []
        class FakeDB:
            def update_server_tunnel(self_inner, name, tunnel_id, tunnel_name, status, updated_at):
                calls.append((name, tunnel_id, tunnel_name, status, updated_at))
        old_db = self.bot.DB
        old_cf = self.bot.CLOUDFLARE
        self.bot.DB = FakeDB()
        self.bot.CLOUDFLARE = types.SimpleNamespace(tunnel_enabled=True)
        server = {
            'name': 'ir1',
            'api_url': 'https://agent.example.com',
            'public_host': '198.51.100.10',
            'xray_port': 443,
            'cf_tunnel_id': '',
            'cf_tunnel_name': '',
        }
        try:
            with self.assertRaises(self.bot.CloudflareError) as ctx:
                self.bot._sync_cloudflare_for_server(server)
        finally:
            self.bot.DB = old_db
            self.bot.CLOUDFLARE = old_cf
        self.assertIn('not tunnel-ready', str(ctx.exception))
        self.assertEqual(calls[0][0], 'ir1')
        self.assertEqual(calls[0][3], 'needs_provision')

    def test_sync_cloudflare_records_collects_warnings(self):
        class FakeDB:
            def list_servers(self_inner, enabled_only=True):
                return [{'name': 'ir1'}]
        old_db = self.bot.DB
        old_cf = self.bot.CLOUDFLARE
        old_sync = self.bot._sync_cloudflare_for_server
        self.bot.DB = FakeDB()
        self.bot.CLOUDFLARE = types.SimpleNamespace(enabled=True)
        self.bot._sync_cloudflare_for_server = lambda server: (_ for _ in ()).throw(self.bot.CloudflareError('boom'))
        try:
            count, names, warnings = self.bot.sync_cloudflare_records()
        finally:
            self.bot.DB = old_db
            self.bot.CLOUDFLARE = old_cf
            self.bot._sync_cloudflare_for_server = old_sync
        self.assertEqual(count, 0)
        self.assertEqual(names, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn('ir1: boom', warnings[0])


class InstallerCloudflareBootstrapTests(unittest.TestCase):
    def test_install_master_runs_bootstrap_cloudflare_step(self):
        text = (ROOT / 'install_master.sh').read_text(encoding='utf-8')
        self.assertIn('run_step "Bootstrapping Cloudflare" bootstrap_cloudflare', text)


if __name__ == '__main__':
    unittest.main()
