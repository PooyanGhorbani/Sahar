from __future__ import annotations

import csv
import functools
import shutil
import subprocess
import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote

import qrcode
import requests

USERNAME_RE = re.compile(r'^[a-zA-Z0-9_-]{3,32}$')
SERVER_NAME_RE = re.compile(r'^[a-zA-Z0-9_.-]{2,64}$')


def load_config(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    data['admin_ids'] = parse_admin_ids(data.get('admin_chat_ids', ''))
    return data



def setup_logging(log_path: str) -> None:
    log_path_obj = Path(log_path)
    log_dir = log_path_obj.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    class NameFilter(logging.Filter):
        def __init__(self, allowed_prefixes=None, min_level=None):
            super().__init__()
            self.allowed_prefixes = tuple(allowed_prefixes or [])
            self.min_level = min_level

        def filter(self, record: logging.LogRecord) -> bool:
            if self.min_level is not None and record.levelno < self.min_level:
                return False
            if not self.allowed_prefixes:
                return True
            return record.name.startswith(self.allowed_prefixes)

    root_logger = logging.getLogger()
    if getattr(root_logger, '_sahar_logging_configured', False):
        return
    root_logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root_logger.addHandler(stream)

    app_handler = logging.FileHandler(log_path_obj, encoding='utf-8')
    app_handler.setFormatter(fmt)
    root_logger.addHandler(app_handler)

    err_handler = logging.FileHandler(log_dir / 'error.log', encoding='utf-8')
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(fmt)
    root_logger.addHandler(err_handler)

    bot_handler = logging.FileHandler(log_dir / 'bot.log', encoding='utf-8')
    bot_handler.setFormatter(fmt)
    bot_handler.addFilter(NameFilter(['bot']))
    root_logger.addHandler(bot_handler)

    sched_handler = logging.FileHandler(log_dir / 'scheduler.log', encoding='utf-8')
    sched_handler.setFormatter(fmt)
    sched_handler.addFilter(NameFilter(['scheduler']))
    root_logger.addHandler(sched_handler)

    prov_handler = logging.FileHandler(log_dir / 'provision.log', encoding='utf-8')
    prov_handler.setFormatter(fmt)
    prov_handler.addFilter(NameFilter(['provisioner', 'cloudflare_manager', 'agent_client', 'register_local']))
    root_logger.addHandler(prov_handler)

    root_logger._sahar_logging_configured = True


def parse_admin_ids(raw: str) -> List[str]:
    values = []
    for item in str(raw).split(','):
        item = item.strip()
        if item:
            values.append(item)
    return values


def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username))


def valid_server_name(name: str) -> bool:
    return bool(SERVER_NAME_RE.fullmatch(name))


def calc_expire(days: int) -> str:
    return (datetime.utcnow() + timedelta(days=days)).strftime('%Y-%m-%d')


def add_days(date_str: str, more_days: int) -> str:
    base = datetime.strptime(date_str, '%Y-%m-%d')
    return (base + timedelta(days=more_days)).strftime('%Y-%m-%d')


def today_utc() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d')


def date_after_days(days: int) -> str:
    return (datetime.utcnow().date() + timedelta(days=days)).strftime('%Y-%m-%d')


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def bytes_to_gb(value: int) -> float:
    return round(value / (1024 ** 3), 3)





@functools.lru_cache(maxsize=1)
def detect_service_manager() -> str:
    if os.path.isdir('/run/systemd/system') and shutil.which('systemctl'):
        return 'systemd'
    if shutil.which('rc-service'):
        return 'openrc'
    if shutil.which('systemctl'):
        return 'systemd'
    return 'unknown'


def pick_primary_profile(user: Dict) -> Dict:
    transport_mode = str(user.get('transport_mode') or '').lower()
    has_reality = bool(user.get('reality_server_name') and user.get('reality_public_key'))
    if transport_mode == 'reality':
        profile_key = 'reality'
    elif transport_mode == 'dual' and has_reality:
        profile_key = 'reality'
    else:
        profile_key = 'simple'

    if profile_key == 'reality':
        port = int(user.get('reality_port') or user.get('xray_port') or user.get('simple_port') or 0)
    else:
        port = int(user.get('simple_port') or user.get('xray_port') or 0)

    return {
        'public_host': user['public_host'],
        'port': port,
        'profile_key': profile_key,
        'reality_server_name': user.get('reality_server_name') or '',
        'reality_public_key': user.get('reality_public_key') or '',
        'reality_short_id': user.get('reality_short_id') or '',
        'fingerprint': user.get('fingerprint') or 'chrome',
    }

def build_vless_link_for_profile(uuid_value: str, username: str, profile: Dict) -> str:
    host = profile['public_host']
    port = int(profile['port'])
    username_q = quote(username)
    profile_key = (profile.get('profile_key') or 'simple').lower()
    fingerprint = profile.get('fingerprint') or 'chrome'

    if profile_key == 'reality':
        sni = quote(profile.get('reality_server_name') or '')
        public_key = quote(profile.get('reality_public_key') or '')
        short_id = quote(profile.get('reality_short_id') or '')
        return (
            f"vless://{uuid_value}@{host}:{port}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni={sni}&fp={fingerprint}&pbk={public_key}&sid={short_id}&type=tcp#{username_q}"
        )

    return f"vless://{uuid_value}@{host}:{port}?encryption=none&security=none&type=tcp#{username_q}"

def build_vless_link(user: Dict) -> str:
    profile = pick_primary_profile(user)
    return build_vless_link_for_profile(user['uuid'], user['username'], profile)


def write_qr_file(link: str, output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img = qrcode.make(link)
    img.save(path)
    return str(path)


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def export_users_csv(path: str, users: Iterable[Dict]) -> str:
    fields = [
        'username', 'server_name', 'uuid', 'traffic_gb', 'used_gb', 'expire_date',
        'credit_balance', 'is_active', 'plan', 'notes', 'created_at', 'updated_at',
    ]
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for user in users:
            writer.writerow({key: user.get(key, '') for key in fields})
    return path


def systemctl_is_active(service_name: str) -> bool:
    try:
        manager = detect_service_manager()
        if manager == 'systemd':
            subprocess.check_call(['systemctl', 'is-active', '--quiet', service_name])
            return True
        if manager == 'openrc':
            return subprocess.run(['rc-service', service_name, 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False
    return False


def send_telegram_message(bot_token: str, chat_ids: Iterable[str], text: str) -> None:
    for chat_id in chat_ids:
        requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            data={'chat_id': chat_id, 'text': text},
            timeout=20,
        )


def send_telegram_document(bot_token: str, chat_ids: Iterable[str], path: str, caption: Optional[str] = None) -> None:
    for chat_id in chat_ids:
        with open(path, 'rb') as fh:
            requests.post(
                f'https://api.telegram.org/bot{bot_token}/sendDocument',
                data={'chat_id': chat_id, 'caption': caption or ''},
                files={'document': fh},
                timeout=120,
            )
