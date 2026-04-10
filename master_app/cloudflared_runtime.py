from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from utils import detect_service_manager

SERVICE_NAME = 'sahar-cloudflared'
BINARY_PATH = '/usr/local/bin/cloudflared'
SYSTEMD_SERVICE_PATH = Path(f'/etc/systemd/system/{SERVICE_NAME}.service')
OPENRC_SERVICE_PATH = Path(f'/etc/init.d/{SERVICE_NAME}')
ENV_DIR = Path('/etc/sahar')
TOKEN_ENV_PATH = ENV_DIR / 'cloudflared.env'
WRAPPER_PATH = Path('/usr/local/libexec/sahar-cloudflared.sh')
CLOUDFLARED_VERSION = '2026.2.0'


class CloudflaredRuntimeError(RuntimeError):
    pass


def _asset_name(machine: str) -> str:
    machine = (machine or '').strip().lower()
    mapping = {
        'x86_64': 'cloudflared-linux-amd64',
        'amd64': 'cloudflared-linux-amd64',
        'x64': 'cloudflared-linux-amd64',
        'i386': 'cloudflared-linux-386',
        'i686': 'cloudflared-linux-386',
        'aarch64': 'cloudflared-linux-arm64',
        'arm64': 'cloudflared-linux-arm64',
        'armv8': 'cloudflared-linux-arm64',
        'armv7l': 'cloudflared-linux-arm',
        'armv6l': 'cloudflared-linux-arm',
        'arm': 'cloudflared-linux-arm',
    }
    asset = mapping.get(machine)
    if not asset:
        raise CloudflaredRuntimeError(f'unsupported architecture for cloudflared: {machine}')
    return asset


def _release_asset_metadata(asset_name: str) -> tuple[str, str]:
    url = f'https://api.github.com/repos/cloudflare/cloudflared/releases/tags/{CLOUDFLARED_VERSION}'
    req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Sahar/0.1.61'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    for asset in data.get('assets', []):
        if asset.get('name') != asset_name:
            continue
        digest = str(asset.get('digest') or '')
        digest = digest.split(':', 1)[-1].strip() if digest else ''
        download_url = asset.get('browser_download_url') or ''
        if not download_url:
            break
        return download_url, digest
    raise CloudflaredRuntimeError(f'could not resolve cloudflared asset metadata for {asset_name}')


def install_binary(dest_path: str = BINARY_PATH) -> str:
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and os.access(dest, os.X_OK):
        return str(dest)
    machine = subprocess.check_output(['uname', '-m'], text=True).strip()
    asset_name = _asset_name(machine)
    url, digest = _release_asset_metadata(asset_name)
    fd, tmp_path = tempfile.mkstemp(prefix='cloudflared-', suffix='.bin')
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Sahar/0.1.61'})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, 'wb') as fh:
            shutil.copyfileobj(resp, fh)
        if digest:
            actual = hashlib.sha256(Path(tmp_path).read_bytes()).hexdigest()
            if actual.lower() != digest.lower():
                raise CloudflaredRuntimeError('cloudflared checksum verification failed')
        current_mode = os.stat(tmp_path).st_mode
        os.chmod(tmp_path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        shutil.move(tmp_path, dest)
    except Exception as exc:
        raise CloudflaredRuntimeError(f'failed to install cloudflared: {exc}') from exc
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return str(dest)


def _read_env_token() -> str:
    try:
        for line in TOKEN_ENV_PATH.read_text(encoding='utf-8').splitlines():
            if line.startswith('TUNNEL_TOKEN='):
                return line.split('=', 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        return ''
    return ''


def current_configured_token(manager: str) -> str:
    if manager not in {'systemd', 'openrc'}:
        return ''
    return _read_env_token()


def service_is_installed(manager: str) -> bool:
    if manager == 'systemd':
        return SYSTEMD_SERVICE_PATH.exists() and TOKEN_ENV_PATH.exists()
    if manager == 'openrc':
        return OPENRC_SERVICE_PATH.exists() and TOKEN_ENV_PATH.exists()
    return False


def _write_wrapper_and_env(token: str) -> None:
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_ENV_PATH.write_text(f"TUNNEL_TOKEN='{token}'\n", encoding='utf-8')
    TOKEN_ENV_PATH.chmod(0o600)
    WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER_PATH.write_text(
        '\n'.join([
            '#!/bin/sh',
            'set -eu',
            f'. {TOKEN_ENV_PATH}',
            f'exec {BINARY_PATH} tunnel --no-autoupdate run --token "$TUNNEL_TOKEN"',
            '',
        ]),
        encoding='utf-8',
    )
    WRAPPER_PATH.chmod(0o700)


def _write_systemd_service(token: str) -> None:
    _write_wrapper_and_env(token)
    SYSTEMD_SERVICE_PATH.write_text(
        '\n'.join([
            '[Unit]',
            'Description=Sahar Cloudflare Tunnel',
            'After=network-online.target',
            'Wants=network-online.target',
            '',
            '[Service]',
            'Type=simple',
            f'ExecStart={WRAPPER_PATH}',
            'Restart=always',
            'RestartSec=5',
            '',
            '[Install]',
            'WantedBy=multi-user.target',
            '',
        ]),
        encoding='utf-8',
    )
    subprocess.check_call(['systemctl', 'daemon-reload'])
    subprocess.run(['systemctl', 'enable', SERVICE_NAME], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE_NAME]).returncode == 0:
        subprocess.check_call(['systemctl', 'restart', SERVICE_NAME])
    else:
        subprocess.check_call(['systemctl', 'start', SERVICE_NAME])


def _write_openrc_service(token: str) -> None:
    _write_wrapper_and_env(token)
    OPENRC_SERVICE_PATH.write_text(
        '\n'.join([
            '#!/sbin/openrc-run',
            f'name="{SERVICE_NAME}"',
            f'command="{WRAPPER_PATH}"',
            'command_background=true',
            f'pidfile="/run/{SERVICE_NAME}.pid"',
            'output_log="/var/log/sahar-cloudflared.log"',
            'error_log="/var/log/sahar-cloudflared.err"',
            '',
            'depend() {',
            '    need net',
            '}',
            '',
        ]),
        encoding='utf-8',
    )
    OPENRC_SERVICE_PATH.chmod(0o755)
    subprocess.run(['rc-update', 'add', SERVICE_NAME, 'default'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    status_rc = subprocess.run(['rc-service', SERVICE_NAME, 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    if status_rc == 0:
        subprocess.check_call(['rc-service', SERVICE_NAME, 'restart'])
        return
    subprocess.check_call(['rc-service', SERVICE_NAME, 'start'])


def deploy_local_service(token: str) -> None:
    if not token:
        raise CloudflaredRuntimeError('cloudflared token is required')
    manager = detect_service_manager()
    current_token = current_configured_token(manager)
    if current_token == token and service_is_installed(manager):
        return
    if os.geteuid() != 0:
        raise CloudflaredRuntimeError('cloudflared runtime changes require root privileges')
    install_binary()
    if manager == 'systemd':
        _write_systemd_service(token)
        return
    if manager == 'openrc':
        _write_openrc_service(token)
        return
    raise CloudflaredRuntimeError(f'unsupported init system for cloudflared: {manager}')
