from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Flask, jsonify, request, send_file

from utils import load_config, now_iso, parse_allowed_sources, safe_compare, save_config, setup_logging, source_allowed, xray_version
from xray_manager import XrayManager

CONFIG_PATH = os.environ.get('SAHAR_CONFIG', '/opt/sahar-agent/data/config.json')
CONFIG = load_config(CONFIG_PATH)
setup_logging(CONFIG['log_path'])
LOGGER = logging.getLogger('agent_api')
APP = Flask(__name__)
XRAY = XrayManager(CONFIG)
INITIALIZED = False
ALLOWED_SOURCES = parse_allowed_sources(CONFIG.get('allowed_sources', ''))
RATE_LIMIT_WINDOW = int(CONFIG.get('rate_limit_window_seconds', 60))
RATE_LIMIT_MAX = int(CONFIG.get('rate_limit_max_requests', 120))
RATE_BUCKETS: dict[str, deque] = defaultdict(deque)


def initialize_runtime(restart_if_needed: bool = False) -> None:
    global INITIALIZED, CONFIG, XRAY, ALLOWED_SOURCES, RATE_LIMIT_WINDOW, RATE_LIMIT_MAX
    if INITIALIZED:
        return
    CONFIG = load_config(CONFIG_PATH)
    ALLOWED_SOURCES = parse_allowed_sources(CONFIG.get('allowed_sources', ''))
    RATE_LIMIT_WINDOW = int(CONFIG.get('rate_limit_window_seconds', 60))
    RATE_LIMIT_MAX = int(CONFIG.get('rate_limit_max_requests', 120))
    setup_logging(CONFIG['log_path'])
    XRAY = XrayManager(CONFIG)
    runtime = XRAY.ensure_runtime_settings()
    if runtime['updated']:
        save_config(CONFIG_PATH, runtime['config'])
        CONFIG = runtime['config']
        XRAY = XrayManager(CONFIG)
    XRAY.ensure_base_config()
    if restart_if_needed and not XRAY.is_active():
        try:
            XRAY.restart_service()
        except Exception:
            LOGGER.exception('initial_xray_restart_failed')
    INITIALIZED = True


def ok(data=None, status: int = 200):
    return jsonify({'ok': True, 'data': data or {}}), status


def fail(message: str, status: int = 400):
    return jsonify({'ok': False, 'error': message}), status


def within_rate_limit(key: str) -> bool:
    now = time.time()
    bucket = RATE_BUCKETS[key]
    while bucket and (now - bucket[0]) > RATE_LIMIT_WINDOW:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX:
        return False
    bucket.append(now)
    return True


def require_token(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        initialize_runtime(restart_if_needed=False)
        token = request.headers.get('X-Agent-Token', '')
        remote_ip = request.remote_addr or ''
        if not safe_compare(token, CONFIG.get('agent_token', '')):
            return fail('unauthorized', 401)
        if not source_allowed(remote_ip, ALLOWED_SOURCES):
            return fail('forbidden', 403)
        if not within_rate_limit(f'{remote_ip}:{token[:8]}'):
            return fail('rate limit exceeded', 429)
        return func(*args, **kwargs)
    return wrapper


@APP.get('/health')
@require_token
def health():
    try:
        data = XRAY.health()
    except Exception as exc:
        LOGGER.exception('health_failed')
        data = {
            'agent_name': CONFIG.get('agent_name', ''),
            'public_host': CONFIG.get('public_host', ''),
            'host_mode': CONFIG.get('host_mode', ''),
            'xray_port': CONFIG.get('simple_port') or CONFIG.get('xray_port') or 0,
            'simple_port': CONFIG.get('simple_port') or CONFIG.get('xray_port') or 0,
            'reality_port': CONFIG.get('reality_port') or 0,
            'transport_mode': CONFIG.get('transport_mode', 'ws'),
            'ws_path': CONFIG.get('ws_path', '/ws'),
            'reality_server_name': CONFIG.get('reality_server_name', ''),
            'reality_public_key': CONFIG.get('reality_public_key', ''),
            'reality_short_id': CONFIG.get('reality_short_id', ''),
            'fingerprint': CONFIG.get('fingerprint', 'chrome'),
            'xray_active': False,
            'user_count': 0,
            'profiles': [],
            'health_warning': str(exc),
            'tls_enabled': bool(CONFIG.get('agent_tls_enabled', False)),
            'tls_fingerprint': CONFIG.get('agent_tls_fingerprint', ''),
        }
    data['server_time'] = now_iso()
    return ok(data)


@APP.get('/config/summary')
@require_token
def config_summary():
    return ok(
        {
            'agent_name': CONFIG.get('agent_name', ''),
            'public_host': CONFIG.get('public_host', ''),
            'host_mode': CONFIG.get('host_mode', ''),
            'transport_mode': CONFIG.get('transport_mode', 'ws'),
            'ws_path': CONFIG.get('ws_path', '/ws'),
            'xray_port': CONFIG.get('simple_port') or CONFIG.get('xray_port'),
            'simple_port': CONFIG.get('simple_port') or CONFIG.get('xray_port'),
            'reality_port': CONFIG.get('reality_port'),
            'xray_api_port': CONFIG.get('xray_api_port'),
            'allowed_sources': ALLOWED_SOURCES,
            'rate_limit_window_seconds': RATE_LIMIT_WINDOW,
            'rate_limit_max_requests': RATE_LIMIT_MAX,
            'tls_enabled': bool(CONFIG.get('agent_tls_enabled', False)),
            'tls_fingerprint': CONFIG.get('agent_tls_fingerprint', ''),
        }
    )



@APP.get('/profiles')
@require_token
def profiles_list():
    return ok({'profiles': XRAY.profile_summaries()})


@APP.get('/users/list')
@require_token
def users_list():
    return ok({'users': XRAY.list_clients()})


@APP.post('/users/add')
@require_token
def users_add():
    payload = request.get_json(force=True)
    username = (payload.get('username') or '').strip()
    uuid_value = (payload.get('uuid') or '').strip()
    if not username or not uuid_value:
        return fail('username and uuid are required')
    try:
        data = XRAY.add_client(username, uuid_value)
        LOGGER.info('user_added username=%s', username)
        return ok({'client': data})
    except Exception as exc:
        LOGGER.exception('user_add_failed username=%s', username)
        return fail(str(exc), 500)


@APP.post('/users/remove')
@require_token
def users_remove():
    payload = request.get_json(force=True)
    username = (payload.get('username') or '').strip()
    if not username:
        return fail('username is required')
    try:
        removed = XRAY.remove_client(username)
        LOGGER.info('user_removed username=%s removed=%s', username, removed)
        return ok({'removed': removed})
    except Exception as exc:
        LOGGER.exception('user_remove_failed username=%s', username)
        return fail(str(exc), 500)


@APP.post('/users/disable')
@require_token
def users_disable():
    payload = request.get_json(force=True)
    username = (payload.get('username') or '').strip()
    if not username:
        return fail('username is required')
    try:
        removed = XRAY.disable_client(username)
        LOGGER.info('user_disabled username=%s removed=%s', username, removed)
        return ok({'disabled': removed})
    except Exception as exc:
        LOGGER.exception('user_disable_failed username=%s', username)
        return fail(str(exc), 500)


@APP.post('/users/enable')
@require_token
def users_enable():
    payload = request.get_json(force=True)
    username = (payload.get('username') or '').strip()
    uuid_value = (payload.get('uuid') or '').strip()
    if not username or not uuid_value:
        return fail('username and uuid are required')
    try:
        data = XRAY.enable_client(username, uuid_value)
        LOGGER.info('user_enabled username=%s', username)
        return ok({'client': data})
    except Exception as exc:
        LOGGER.exception('user_enable_failed username=%s', username)
        return fail(str(exc), 500)


@APP.get('/users/stats')
@require_token
def users_stats():
    username = (request.args.get('username') or '').strip()
    if not username:
        return fail('username is required')
    try:
        data = XRAY.get_user_stats(username)
        return ok(data)
    except Exception as exc:
        LOGGER.exception('user_stats_failed username=%s', username)
        return fail(str(exc), 500)


@APP.get('/users/all-stats')
@require_token
def users_all_stats():
    try:
        return ok({'stats': XRAY.all_user_stats()})
    except Exception as exc:
        LOGGER.exception('all_user_stats_failed')
        return fail(str(exc), 500)


@APP.post('/xray/restart')
@require_token
def xray_restart():
    try:
        XRAY.restart_service()
        LOGGER.info('xray_restart')
        return ok({'restarted': True, 'at': now_iso()})
    except Exception as exc:
        LOGGER.exception('xray_restart_failed')
        return fail(str(exc), 500)


@APP.post('/backup/create')
@require_token
def backup_create():
    try:
        data = XRAY.create_backup(CONFIG_PATH)
        return ok(data)
    except Exception as exc:
        LOGGER.exception('backup_create_failed')
        return fail(str(exc), 500)


@APP.get('/backup/download/<path:filename>')
@require_token
def backup_download(filename: str):
    full_path = os.path.join(CONFIG.get('backup_dir', '/opt/sahar-agent/backups'), os.path.basename(filename))
    if not os.path.exists(full_path):
        return fail('backup not found', 404)
    return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))


@APP.get('/version')
@require_token
def version():
    return ok(
        {
            'service': 'sahar-agent',
            'package_version': CONFIG.get('package_version', ''),
            'agent_name': CONFIG.get('agent_name', ''),
            'xray_version': xray_version(),
            'time': now_iso(),
        }
    )


if __name__ == '__main__':
    initialize_runtime(restart_if_needed=True)
    APP.run(host=CONFIG.get('agent_listen_host', '0.0.0.0'), port=int(CONFIG.get('agent_listen_port', 8787)), debug=False)
