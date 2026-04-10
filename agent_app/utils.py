from __future__ import annotations

import functools
import hmac
import ipaddress
import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def _resolve_config_path(path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(str(path))))


def load_config(path: str) -> Dict:
    with open(_resolve_config_path(path), 'r', encoding='utf-8') as fh:
        return json.load(fh)


def save_config(path: str, data: Dict) -> None:
    path_obj = _resolve_config_path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path_obj.name + '.', suffix='.tmp', dir=str(path_obj.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path_obj)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def setup_logging(log_path: str) -> None:
    log_path_obj = _resolve_config_path(log_path)
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
    root_logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    configured_paths = set(getattr(root_logger, '_sahar_logging_paths', set()))

    if not getattr(root_logger, '_sahar_logging_configured', False):
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root_logger.addHandler(stream)
        root_logger._sahar_logging_stream = stream
        root_logger._sahar_logging_configured = True
    else:
        stream = getattr(root_logger, '_sahar_logging_stream', None)

    def add_file_handler(path: Path, *, level=None, prefixes=None):
        key = str(path)
        if key in configured_paths:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handler = logging.FileHandler(path, encoding='utf-8')
        except (PermissionError, OSError) as exc:
            if stream is not None:
                stream.setLevel(logging.WARNING)
            root_logger.warning('could not open log file %s: %s', path, exc)
            return
        if level is not None:
            handler.setLevel(level)
        handler.setFormatter(fmt)
        if prefixes:
            handler.addFilter(NameFilter(prefixes))
        root_logger.addHandler(handler)
        configured_paths.add(key)

    add_file_handler(log_path_obj)
    add_file_handler(log_dir / 'error.log', level=logging.ERROR)
    add_file_handler(log_dir / 'api.log', prefixes=['agent_api'])
    add_file_handler(log_dir / 'xray.log', prefixes=['xray_manager'])
    root_logger._sahar_logging_paths = configured_paths


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def generate_short_id(length: int = 8) -> str:
    return secrets.token_hex(length // 2)


def run_command(args: List[str]) -> str:
    return subprocess.check_output(args, stderr=subprocess.STDOUT, text=True)


def generate_x25519_keypair() -> Tuple[str, str]:
    output = run_command(['xray', 'x25519'])
    private_key = ''
    public_key = ''
    for line in output.splitlines():
        lower = line.lower().strip()
        if lower.startswith('private key:'):
            private_key = line.split(':', 1)[1].strip()
        if lower.startswith('public key:'):
            public_key = line.split(':', 1)[1].strip()
    if not private_key or not public_key:
        raise RuntimeError('failed to parse x25519 key pair')
    return private_key, public_key


def parse_allowed_sources(raw: str) -> List[str]:
    normalized: List[str] = []
    for item in str(raw).split(','):
        item = item.strip()
        if not item:
            continue
        if item.upper() == 'ANY' or item == '*':
            return ['*']
        normalized.append(item)
    return normalized


def source_allowed(remote_ip: str, allowed_sources: Iterable[str]) -> bool:
    allowed = list(allowed_sources)
    if '*' in allowed:
        return True
    if not allowed:
        return False
    try:
        ip_obj = ipaddress.ip_address((remote_ip or '').strip())
    except ValueError:
        return False
    for item in allowed:
        try:
            if '/' in item:
                if ip_obj in ipaddress.ip_network(item, strict=False):
                    return True
            elif ip_obj == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue
    return False


def safe_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a), str(b))


@functools.lru_cache(maxsize=1)
def detect_service_manager() -> str:
    if os.path.isdir('/run/systemd/system') and shutil.which('systemctl'):
        return 'systemd'
    if shutil.which('rc-service'):
        return 'openrc'
    if shutil.which('systemctl'):
        return 'systemd'
    return 'unknown'


def service_restart(service_name: str) -> None:
    manager = detect_service_manager()
    if manager == 'systemd':
        subprocess.check_call(['systemctl', 'restart', service_name])
        return
    if manager == 'openrc':
        result = subprocess.run(['rc-service', service_name, 'restart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            subprocess.check_call(['rc-service', service_name, 'start'])
        return
    raise RuntimeError(f'unsupported service manager for restart: {manager}')


def service_is_active(service_name: str) -> bool:
    manager = detect_service_manager()
    try:
        if manager == 'systemd':
            subprocess.check_call(['systemctl', 'is-active', '--quiet', service_name])
            return True
        if manager == 'openrc':
            return subprocess.run(['rc-service', service_name, 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False
    return False


def xray_version() -> str:
    try:
        out = run_command(['xray', 'version'])
        return out.splitlines()[0].strip()
    except Exception:
        return 'unknown'


def system_metrics() -> Dict:
    import psutil
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = psutil.boot_time()
    uptime_seconds = max(0, int(time.time() - boot_time))
    return {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'memory_percent': round(vm.percent, 2),
        'memory_used_mb': round(vm.used / (1024 ** 2), 1),
        'memory_total_mb': round(vm.total / (1024 ** 2), 1),
        'disk_percent': round(disk.percent, 2),
        'disk_used_gb': round(disk.used / (1024 ** 3), 2),
        'disk_total_gb': round(disk.total / (1024 ** 3), 2),
        'load_1m': round(load1, 2),
        'load_5m': round(load5, 2),
        'load_15m': round(load15, 2),
        'uptime_seconds': uptime_seconds,
        'xray_version': xray_version(),
    }
