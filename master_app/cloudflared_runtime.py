from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from utils import detect_service_manager

SERVICE_NAME = 'sahar-cloudflared'
BINARY_PATH = '/usr/local/bin/cloudflared'
SYSTEMD_SERVICE_PATH = Path(f'/etc/systemd/system/{SERVICE_NAME}.service')
OPENRC_SERVICE_PATH = Path(f'/etc/init.d/{SERVICE_NAME}')
TOKEN_RE = re.compile(r'--token\s+([^"\s]+)')


class CloudflaredRuntimeError(RuntimeError):
    pass


def _download_url(machine: str) -> str:
    machine = (machine or '').strip().lower()
    mapping = {
        'x86_64': 'amd64',
        'amd64': 'amd64',
        'x64': 'amd64',
        'i386': '386',
        'i686': '386',
        'aarch64': 'arm64',
        'arm64': 'arm64',
        'armv8': 'arm64',
        'armv7l': 'arm',
        'armv6l': 'arm',
        'arm': 'arm',
    }
    suffix = mapping.get(machine)
    if not suffix:
        raise CloudflaredRuntimeError(f'unsupported architecture for cloudflared: {machine}')
    return f'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{suffix}'


def install_binary(dest_path: str = BINARY_PATH) -> str:
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and os.access(dest, os.X_OK):
        return str(dest)
    machine = subprocess.check_output(['uname', '-m'], text=True).strip()
    url = _download_url(machine)
    fd, tmp_path = tempfile.mkstemp(prefix='cloudflared-', suffix='.bin')
    os.close(fd)
    try:
        subprocess.check_call(['curl', '-fsSL', url, '-o', tmp_path])
        current_mode = os.stat(tmp_path).st_mode
        os.chmod(tmp_path, current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        shutil.move(tmp_path, dest)
    except Exception as exc:
        raise CloudflaredRuntimeError(f'failed to install cloudflared: {exc}') from exc
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return str(dest)


def _extract_token(path: Path) -> str:
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''
    match = TOKEN_RE.search(text)
    return match.group(1) if match else ''


def current_configured_token(manager: str) -> str:
    if manager == 'systemd':
        return _extract_token(SYSTEMD_SERVICE_PATH)
    if manager == 'openrc':
        return _extract_token(OPENRC_SERVICE_PATH)
    return ''


def service_is_installed(manager: str) -> bool:
    if manager == 'systemd':
        return SYSTEMD_SERVICE_PATH.exists()
    if manager == 'openrc':
        return OPENRC_SERVICE_PATH.exists()
    return False


def _write_systemd_service(token: str) -> None:
    SYSTEMD_SERVICE_PATH.write_text(
        '\n'.join([
            '[Unit]',
            'Description=Sahar Cloudflare Tunnel',
            'After=network-online.target',
            'Wants=network-online.target',
            '',
            '[Service]',
            'Type=simple',
            f'ExecStart={BINARY_PATH} tunnel --no-autoupdate run --token {token}',
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
    OPENRC_SERVICE_PATH.write_text(
        '\n'.join([
            '#!/sbin/openrc-run',
            f'name="{SERVICE_NAME}"',
            f'command="{BINARY_PATH}"',
            f'command_args="tunnel --no-autoupdate run --token {token}"',
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
