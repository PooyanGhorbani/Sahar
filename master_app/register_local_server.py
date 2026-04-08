from __future__ import annotations

import logging
import os
from pathlib import Path

from agent_client import AgentClient, AgentError
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


def _local_agent_config_path() -> Path:
    return Path(CONFIG_PATH).with_name('local-agent-config.json')


def _fallback_server_payload(name: str, api_url: str, api_token: str) -> dict:
    payload = {
        'name': name,
        'api_url': api_url,
        'api_token': api_token,
        'public_host': '',
        'host_mode': 'ip',
        'xray_port': 0,
        'transport_mode': 'dual',
        'reality_server_name': '',
        'reality_public_key': '',
        'reality_short_id': '',
        'fingerprint': 'chrome',
        'reality_port': 0,
        'enabled': True,
        'last_health_status': 'warn',
        'xray_active': False,
        'last_health_message': 'local agent health unavailable during registration',
        'last_health_at': now_iso(),
        'provisioning_state': 'healthy',
        'provisioning_message': 'local agent registered with fallback metadata',
        'updated_at': now_iso(),
    }
    local_cfg_path = _local_agent_config_path()
    if local_cfg_path.exists():
        try:
            local_cfg = load_config(str(local_cfg_path))
            payload.update({
                'public_host': local_cfg.get('public_host', payload['public_host']),
                'host_mode': local_cfg.get('host_mode', payload['host_mode']),
                'xray_port': int(local_cfg.get('simple_port') or local_cfg.get('xray_port') or payload['xray_port'] or 0),
                'transport_mode': local_cfg.get('transport_mode', payload['transport_mode']),
                'reality_server_name': local_cfg.get('reality_server_name', payload['reality_server_name']),
                'fingerprint': local_cfg.get('fingerprint', payload['fingerprint']),
                'reality_port': int(local_cfg.get('reality_port') or payload['reality_port'] or 0),
            })
        except Exception:
            LOGGER.exception('failed_to_read_local_agent_config path=%s', local_cfg_path)
    return payload


def _fetch_local_agent_metadata(client: AgentClient) -> dict:
    errors = []
    try:
        data = client.health().get('data', {})
        if data:
            return data
    except Exception as exc:
        errors.append(f'health failed: {exc}')
        LOGGER.warning('local_agent_health_failed exc=%s', exc)
    try:
        data = client.config_summary().get('data', {})
        if data:
            return data
    except Exception as exc:
        errors.append(f'config summary failed: {exc}')
        LOGGER.warning('local_agent_config_summary_failed exc=%s', exc)
    raise AgentError('; '.join(errors) if errors else 'agent metadata unavailable')


def register() -> None:
    if not CONFIG.get('local_node_enabled'):
        return
    name = CONFIG.get('local_server_name', 'local')
    api_url = CONFIG.get('local_agent_api_url', 'http://127.0.0.1:8787')
    api_token = CONFIG.get('local_agent_api_token', '')
    if not api_token:
        raise RuntimeError('local agent token missing from config')
    client = AgentClient(api_url, api_token, timeout=int(CONFIG.get('agent_timeout_seconds', 15)))
    try:
        meta = _fetch_local_agent_metadata(client)
        health_status = 'ok'
        health_message = ''
        xray_active = bool(meta.get('xray_active', True))
        provisioning_message = 'local agent registered'
    except Exception as exc:
        LOGGER.exception('local_agent_metadata_unavailable')
        meta = _fallback_server_payload(name, api_url, api_token)
        health_status = meta.get('last_health_status', 'warn')
        health_message = meta.get('last_health_message', str(exc))
        xray_active = bool(meta.get('xray_active', False))
        provisioning_message = meta.get('provisioning_message', 'local agent registered with fallback metadata')

    existing = DB.get_server(name)
    created_at = existing['created_at'] if existing else now_iso()
    DB.add_or_update_server({
        'name': name,
        'api_url': api_url,
        'api_token': api_token,
        'public_host': meta.get('public_host', ''),
        'host_mode': meta.get('host_mode', ''),
        'xray_port': int(meta.get('simple_port') or meta.get('xray_port') or 0),
        'transport_mode': meta.get('transport_mode', 'tcp'),
        'reality_server_name': meta.get('reality_server_name', ''),
        'reality_public_key': meta.get('reality_public_key', ''),
        'reality_short_id': meta.get('reality_short_id', ''),
        'fingerprint': meta.get('fingerprint', 'chrome'),
        'reality_port': int(meta.get('reality_port', 0) or 0),
        'enabled': True,
        'last_health_status': health_status,
        'xray_active': xray_active,
        'last_health_message': health_message,
        'last_health_at': now_iso(),
        'created_at': created_at,
        'provisioning_state': 'healthy',
        'provisioning_message': provisioning_message,
        'updated_at': now_iso(),
    })
    if CF.enabled and meta.get('host_mode') == 'ip' and meta.get('public_host'):
        try:
            info = CF.ensure_server_dns(name, meta.get('public_host'))
            DB.update_server_dns(name, info['zone_id'], info['record_id'], info['dns_name'], now_iso())
        except Exception as exc:
            record_error(DB, LOGGER, component='cloudflare', target_type='server', target_key=name, message='local cloudflare dns sync failed', exc=exc)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    register()
