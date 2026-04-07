from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from utils import ensure_dir, generate_short_id, generate_x25519_keypair, service_is_active, service_restart, system_metrics


class XrayManager:
    def __init__(self, config: Dict):
        self.config = config
        self.config_path = config['xray_config_path']
        self.public_host = config['public_host']
        self.host_mode = config.get('host_mode', 'ip')
        self.simple_port = int(config.get('simple_port') or config.get('xray_port') or 443)
        self.reality_port = int(config.get('reality_port') or 8443)
        self.api_port = int(config.get('xray_api_port', 10085))
        self.reality_server_name = config.get('reality_server_name', '')
        self.reality_dest = config.get('reality_dest', '')
        self.reality_private_key = config.get('reality_private_key', '')
        self.reality_public_key = config.get('reality_public_key', '')
        self.reality_short_id = config.get('reality_short_id', '')
        self.fingerprint = config.get('fingerprint', 'chrome')
        self.backup_dir = config.get('backup_dir', '/opt/sahar-agent/backups')

    def ensure_runtime_settings(self) -> Dict:
        updated = False
        if not self.reality_private_key or not self.reality_public_key:
            private_key, public_key = generate_x25519_keypair()
            self.config['reality_private_key'] = private_key
            self.config['reality_public_key'] = public_key
            self.reality_private_key = private_key
            self.reality_public_key = public_key
            updated = True
        if not self.reality_short_id:
            short_id = generate_short_id(8)
            self.config['reality_short_id'] = short_id
            self.reality_short_id = short_id
            updated = True
        if not self.reality_dest and self.reality_server_name:
            self.reality_dest = f'{self.reality_server_name}:443'
            self.config['reality_dest'] = self.reality_dest
            updated = True
        return {'updated': updated, 'config': self.config}

    def save_runtime_config(self, path: str) -> None:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(self.config, fh, indent=2)

    def ensure_base_config(self) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        if os.path.exists(self.config_path):
            try:
                current = self._load()
                if current.get('inbounds'):
                    return
            except Exception:
                pass
        base = self._build_base_config([], [])
        self._save_atomic(base)

    def _simple_inbound(self, clients: List[Dict]) -> Dict:
        return {
            'tag': 'vless-simple',
            'listen': '0.0.0.0',
            'port': self.simple_port,
            'protocol': 'vless',
            'settings': {'clients': clients, 'decryption': 'none'},
            'sniffing': {'enabled': True, 'destOverride': ['http', 'tls', 'quic']},
            'streamSettings': {'network': 'tcp', 'security': 'none'},
        }

    def _reality_inbound(self, clients: List[Dict]) -> Dict:
        if not self.reality_server_name:
            raise RuntimeError('reality_server_name is required')
        return {
            'tag': 'vless-reality',
            'listen': '0.0.0.0',
            'port': self.reality_port,
            'protocol': 'vless',
            'settings': {'clients': clients, 'decryption': 'none'},
            'sniffing': {'enabled': True, 'destOverride': ['http', 'tls', 'quic']},
            'streamSettings': {
                'network': 'tcp',
                'security': 'reality',
                'realitySettings': {
                    'show': False,
                    'dest': self.reality_dest,
                    'xver': 0,
                    'serverNames': [self.reality_server_name],
                    'privateKey': self.reality_private_key,
                    'shortIds': [self.reality_short_id],
                },
            },
        }

    def _build_base_config(self, simple_clients: List[Dict], reality_clients: List[Dict]) -> Dict:
        return {
            'log': {
                'access': self.config.get('xray_access_log', '/var/log/xray/access.log'),
                'error': self.config.get('xray_error_log', '/var/log/xray/error.log'),
                'loglevel': 'warning',
            },
            'api': {'tag': 'api', 'services': ['HandlerService', 'StatsService']},
            'policy': {
                'levels': {'0': {'statsUserUplink': True, 'statsUserDownlink': True}},
                'system': {
                    'statsInboundUplink': True,
                    'statsInboundDownlink': True,
                    'statsOutboundUplink': True,
                    'statsOutboundDownlink': True,
                },
            },
            'stats': {},
            'inbounds': [
                self._simple_inbound(simple_clients),
                self._reality_inbound(reality_clients),
                {
                    'tag': 'api',
                    'listen': '127.0.0.1',
                    'port': self.api_port,
                    'protocol': 'dokodemo-door',
                    'settings': {'address': '127.0.0.1'},
                },
            ],
            'outbounds': [
                {'tag': 'direct', 'protocol': 'freedom', 'settings': {}},
                {'tag': 'blocked', 'protocol': 'blackhole', 'settings': {}},
            ],
            'routing': {'rules': [{'type': 'field', 'inboundTag': ['api'], 'outboundTag': 'api'}]},
        }

    def _load(self) -> Dict:
        with open(self.config_path, 'r', encoding='utf-8') as fh:
            return json.load(fh)

    def _save_atomic(self, data: Dict) -> None:
        backup = self.config_path + '.bak'
        if os.path.exists(self.config_path):
            shutil.copy2(self.config_path, backup)
        fd, tmp_path = tempfile.mkstemp(prefix='xray_', suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2)
            subprocess.check_call(['xray', 'run', '-test', '-config', tmp_path])
            shutil.move(tmp_path, self.config_path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _find_inbound(self, data: Dict, tag: str) -> Dict:
        for inbound in data.get('inbounds', []):
            if inbound.get('tag') == tag:
                return inbound
        raise KeyError(f'inbound not found: {tag}')

    def list_clients(self) -> List[Dict]:
        data = self._load()
        return self._find_inbound(data, 'vless-simple')['settings']['clients']

    def add_client(self, username: str, uuid_value: str) -> Dict:
        data = self._load()
        simple_clients = self._find_inbound(data, 'vless-simple')['settings']['clients']
        reality_clients = self._find_inbound(data, 'vless-reality')['settings']['clients']
        for client in simple_clients:
            if client.get('email') == username:
                return client
        simple_client = {'id': uuid_value, 'email': username, 'level': 0}
        reality_client = {'id': uuid_value, 'email': username, 'level': 0, 'flow': 'xtls-rprx-vision'}
        simple_clients.append(simple_client)
        reality_clients.append(reality_client)
        self._save_atomic(data)
        self.restart_service()
        return simple_client

    def remove_client(self, username: str) -> bool:
        data = self._load()
        simple_clients = self._find_inbound(data, 'vless-simple')['settings']['clients']
        reality_clients = self._find_inbound(data, 'vless-reality')['settings']['clients']
        new_simple = [client for client in simple_clients if client.get('email') != username]
        new_reality = [client for client in reality_clients if client.get('email') != username]
        if len(new_simple) == len(simple_clients) and len(new_reality) == len(reality_clients):
            return False
        self._find_inbound(data, 'vless-simple')['settings']['clients'] = new_simple
        self._find_inbound(data, 'vless-reality')['settings']['clients'] = new_reality
        self._save_atomic(data)
        self.restart_service()
        return True

    def disable_client(self, username: str) -> bool:
        return self.remove_client(username)

    def enable_client(self, username: str, uuid_value: str) -> Dict:
        return self.add_client(username, uuid_value)

    def restart_service(self) -> None:
        service_restart('xray')

    def is_active(self) -> bool:
        return service_is_active('xray')

    def profile_summaries(self) -> List[Dict]:
        return [
            {
                'profile_key': 'simple',
                'display_name': 'VLESS | Simple',
                'public_host': self.public_host,
                'port': self.simple_port,
                'enabled': True,
                'security': 'none',
            },
            {
                'profile_key': 'reality',
                'display_name': 'VLESS | Reality',
                'public_host': self.public_host,
                'port': self.reality_port,
                'enabled': True,
                'security': 'reality',
                'reality_server_name': self.reality_server_name,
                'reality_public_key': self.reality_public_key,
                'reality_short_id': self.reality_short_id,
                'fingerprint': self.fingerprint,
            },
        ]

    def health(self) -> Dict:
        metrics = system_metrics()
        return {
            'agent_name': self.config.get('agent_name', ''),
            'public_host': self.public_host,
            'host_mode': self.host_mode,
            'xray_port': self.simple_port,
            'simple_port': self.simple_port,
            'reality_port': self.reality_port,
            'transport_mode': 'dual',
            'reality_server_name': self.reality_server_name,
            'reality_public_key': self.reality_public_key,
            'reality_short_id': self.reality_short_id,
            'fingerprint': self.fingerprint,
            'xray_active': self.is_active(),
            'user_count': len(self.list_clients()) if os.path.exists(self.config_path) else 0,
            'profiles': self.profile_summaries(),
            **metrics,
        }

    def get_user_stats(self, username: str) -> Dict:
        output = subprocess.check_output(['xray', 'api', 'statsquery', f'--server=127.0.0.1:{self.api_port}'], text=True)
        data = json.loads(output)
        uplink = 0
        downlink = 0
        for item in data.get('stat', []):
            name = item.get('name', '')
            value = int(item.get('value', 0))
            if name == f'user>>>{username}>>>traffic>>>uplink':
                uplink = value
            elif name == f'user>>>{username}>>>traffic>>>downlink':
                downlink = value
        return {'uplink_bytes': uplink, 'downlink_bytes': downlink, 'total_bytes': uplink + downlink}

    def all_user_stats(self) -> Dict[str, Dict[str, int]]:
        output = subprocess.check_output(['xray', 'api', 'statsquery', f'--server=127.0.0.1:{self.api_port}'], text=True)
        data = json.loads(output)
        result: Dict[str, Dict[str, int]] = {}
        for item in data.get('stat', []):
            name = item.get('name', '')
            value = int(item.get('value', 0))
            if not name.startswith('user>>>'):
                continue
            parts = name.split('>>>')
            if len(parts) != 4:
                continue
            _, username, _, direction = parts
            if username not in result:
                result[username] = {'uplink_bytes': 0, 'downlink_bytes': 0, 'total_bytes': 0}
            if direction == 'uplink':
                result[username]['uplink_bytes'] = value
            elif direction == 'downlink':
                result[username]['downlink_bytes'] = value
            result[username]['total_bytes'] = result[username]['uplink_bytes'] + result[username]['downlink_bytes']
        return result

    def create_backup(self, app_config_path: str) -> Dict:
        ensure_dir(self.backup_dir)
        stamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        filename = f"{self.config.get('agent_name', 'agent')}-{stamp}.tar.gz"
        output_path = str(Path(self.backup_dir) / filename)
        with tarfile.open(output_path, 'w:gz') as tar:
            tar.add(self.config_path, arcname='xray/config.json')
            if os.path.exists(app_config_path):
                tar.add(app_config_path, arcname='agent/config.json')
        return {'filename': filename, 'path': output_path, 'size_bytes': os.path.getsize(output_path)}
