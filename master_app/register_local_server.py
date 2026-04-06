from __future__ import annotations

import logging
import os

from agent_client import AgentClient
from cloudflare_manager import CloudflareManager
from db import Database
from error_tools import record_error
from utils import load_config, now_iso, setup_logging

CONFIG_PATH = os.environ.get('SAHAR_CONFIG', '/opt/sahar-master/data/config.json')
CONFIG = load_config(CONFIG_PATH)
setup_logging(CONFIG['log_path'])
DB = Database(CONFIG['database_path'])
CF = CloudflareManager(CONFIG, DB)
LOGGER = logging.getLogger('register_local')


def register() -> None:
    if not CONFIG.get('local_node_enabled'):
        return
    name = CONFIG.get('local_server_name', 'local')
    api_url = CONFIG.get('local_agent_api_url', 'http://127.0.0.1:8787')
    api_token = CONFIG.get('local_agent_api_token', '')
    if not api_token:
        raise RuntimeError('local agent token missing from config')
    health = AgentClient(api_url, api_token, timeout=int(CONFIG.get('agent_timeout_seconds', 15))).health()['data']
    existing = DB.get_server(name)
    created_at = existing['created_at'] if existing else now_iso()
    DB.add_or_update_server({
        'name': name,
        'api_url': api_url,
        'api_token': api_token,
        'public_host': health.get('public_host', ''),
        'host_mode': health.get('host_mode', ''),
        'xray_port': int(health.get('xray_port', 0)),
        'transport_mode': health.get('transport_mode', 'tcp'),
        'reality_server_name': health.get('reality_server_name', ''),
        'reality_public_key': health.get('reality_public_key', ''),
        'reality_short_id': health.get('reality_short_id', ''),
        'fingerprint': health.get('fingerprint', 'chrome'),
        'reality_port': int(health.get('reality_port', 0) or 0),
        'enabled': True,
        'last_health_status': 'ok',
        'xray_active': bool(health.get('xray_active', True)),
        'last_health_message': '',
        'last_health_at': now_iso(),
        'created_at': created_at,
        'provisioning_state': 'healthy',
        'provisioning_message': 'local agent registered',
        'updated_at': now_iso(),
    })
    if CF.enabled and health.get('host_mode') == 'ip' and health.get('public_host'):
        try:
            info = CF.ensure_server_dns(name, health.get('public_host'))
            DB.update_server_dns(name, info['zone_id'], info['record_id'], info['dns_name'], now_iso())
        except Exception as exc:
            record_error(DB, LOGGER, component='cloudflare', target_type='server', target_key=name, message='local cloudflare dns sync failed', exc=exc)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    register()
