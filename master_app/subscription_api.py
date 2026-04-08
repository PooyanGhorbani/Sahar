from __future__ import annotations

import base64
import logging
import os
from flask import Flask, Response, jsonify

from db import Database
from utils import build_vless_link_for_profile, load_config, setup_logging

CONFIG_PATH = os.environ.get('SAHAR_CONFIG', '/opt/sahar-master/data/config.json')
CONFIG = load_config(CONFIG_PATH)
setup_logging(CONFIG['log_path'])
LOGGER = logging.getLogger('subscription_api')
DB = Database(CONFIG['database_path'])
APP = Flask(__name__)


def _profiles_for_server(server: dict) -> list[dict]:
    profiles = []
    if server.get('public_host') and int(server.get('xray_port') or 0) > 0:
        profiles.append({
            'profile_key': 'simple',
            'display_name': f"{server['name']} | VLESS | Simple",
            'public_host': server.get('public_host') or '',
            'port': int(server.get('xray_port') or 0),
            'fingerprint': server.get('fingerprint') or 'chrome',
            'transport_mode': server.get('transport_mode') or 'ws',
            'ws_path': server.get('ws_path') or '/ws',
        })
    if server.get('public_host') and int(server.get('reality_port') or 0) > 0 and server.get('reality_public_key') and server.get('reality_server_name'):
        profiles.append({
            'profile_key': 'reality',
            'display_name': f"{server['name']} | VLESS | Reality",
            'public_host': server.get('public_host') or '',
            'port': int(server.get('reality_port') or 0),
            'reality_server_name': server.get('reality_server_name') or '',
            'reality_public_key': server.get('reality_public_key') or '',
            'reality_short_id': server.get('reality_short_id') or '',
            'fingerprint': server.get('fingerprint') or 'chrome',
            'transport_mode': server.get('transport_mode') or 'ws',
            'ws_path': server.get('ws_path') or '/ws',
        })
    return profiles


def _subscription_lines(user: dict) -> list[str]:
    servers = DB.list_user_access_servers(user['username'], enabled_only=True)
    lines = []
    for server in servers:
        for profile in _profiles_for_server(server):
            lines.append(build_vless_link_for_profile(user['uuid'], f"{user['username']} | {profile['display_name']}", profile))
    return lines


@APP.get('/healthz')
def healthz():
    return jsonify({'ok': True, 'service': 'subscription', 'version': CONFIG.get('package_version', '')})


@APP.get('/sub/<token>')
def sub(token: str):
    user = DB.get_user_by_subscription_token(token)
    if not user or not user.get('is_active'):
        return Response('subscription not found', status=404, mimetype='text/plain')
    lines = _subscription_lines(user)
    raw = '\n'.join(lines).strip() + ('\n' if lines else '')
    payload = base64.b64encode(raw.encode('utf-8')).decode('utf-8')
    headers = {'Content-Type': 'text/plain; charset=utf-8'}
    return Response(payload, headers=headers)


@APP.get('/sub-raw/<token>')
def sub_raw(token: str):
    user = DB.get_user_by_subscription_token(token)
    if not user or not user.get('is_active'):
        return Response('subscription not found', status=404, mimetype='text/plain')
    raw = '\n'.join(_subscription_lines(user)).strip() + '\n'
    return Response(raw, mimetype='text/plain')
