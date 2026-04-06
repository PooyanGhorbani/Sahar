
from __future__ import annotations
import ipaddress
import logging
from typing import Any, Dict, Optional
import requests
from cryptography.fernet import Fernet
from db import Database
LOGGER = logging.getLogger('cloudflare')
class CloudflareError(Exception):
    pass
class CloudflareManager:
    def __init__(self, config: Dict[str, Any], db: Database):
        self.config = config
        self.db = db
        self.enabled = bool(config.get('cloudflare_enabled')) and bool(config.get('cloudflare_domain_name') or config.get('cloudflare_zone_name'))
        key = str(config.get('cloudflare_token_encryption_key') or '')
        self._fernet = Fernet(key.encode()) if key else None
        self.base = 'https://api.cloudflare.com/client/v4'
        self.timeout = int(config.get('cloudflare_timeout_seconds', 30))
    def store_token(self, token: str) -> None:
        if not self._fernet:
            raise CloudflareError('cloudflare encryption key missing')
        self.db.set_meta('cloudflare.token.enc', self._fernet.encrypt(token.encode()).decode())
    def get_token(self) -> str:
        if not self._fernet:
            return ''
        enc = self.db.get_meta('cloudflare.token.enc')
        if not enc:
            return ''
        return self._fernet.decrypt(enc.encode()).decode()
    def _headers(self) -> Dict[str, str]:
        token = self.get_token()
        if not token:
            raise CloudflareError('cloudflare token is not configured')
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    def configured_domain_name(self) -> str:
        domain_name = str(self.config.get('cloudflare_domain_name') or self.config.get('cloudflare_zone_name') or '').strip().strip('.')
        if not domain_name:
            raise CloudflareError('cloudflare domain name is not configured')
        return domain_name

    def _request_json(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            resp = requests.request(method, f'{self.base}{path}', headers=self._headers(), params=params, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise CloudflareError(f'cloudflare request failed: {exc}') from exc
        except ValueError as exc:
            raise CloudflareError(f'cloudflare returned invalid JSON: {exc}') from exc
        if not data.get('success'):
            raise CloudflareError(f"cloudflare api error: {data.get('errors')}")
        return data
    def resolve_zone_id(self) -> str:
        cached = self.db.get_meta('cloudflare.zone_id')
        if cached:
            return cached
        domain_name = self.configured_domain_name()
        data = self._request_json('GET', '/zones', params={'name': domain_name})
        result = data.get('result') or []
        if not result:
            raise CloudflareError(f'domain not found in Cloudflare zones: {domain_name}')
        zone_id = result[0]['id']
        self.db.set_meta('cloudflare.zone_id', zone_id)
        return zone_id
    def _record_name(self, server_name: str) -> str:
        zone = self.configured_domain_name()
        base = str(self.config.get('cloudflare_base_subdomain') or '').strip().strip('.')
        if base:
            return f'{server_name}.{base}.{zone}'
        return f'{server_name}.{zone}'
    def ensure_server_dns(self, server_name: str, target_ip: str) -> Dict[str, str]:
        try:
            ipaddress.ip_address(target_ip)
        except ValueError as exc:
            raise CloudflareError(f'invalid IP for DNS record: {target_ip}') from exc
        zone_id = self.resolve_zone_id()
        record_name = self._record_name(server_name)
        payload = {'type': 'A', 'name': record_name, 'content': target_ip, 'ttl': 1, 'proxied': bool(self.config.get('cloudflare_dns_proxied', False))}
        list_data = self._request_json('GET', f'/zones/{zone_id}/dns_records', params={'type': 'A', 'name': record_name})
        rows = list_data.get('result') or []
        if rows:
            record_id = rows[0]['id']
            data = self._request_json('PUT', f'/zones/{zone_id}/dns_records/{record_id}', payload=payload)
            rec = data['result']
        else:
            data = self._request_json('POST', f'/zones/{zone_id}/dns_records', payload=payload)
            rec = data['result']
        return {'zone_id': zone_id, 'record_id': rec['id'], 'dns_name': rec['name']}
    def delete_server_dns(self, server: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        zone_id = str(server.get('cf_zone_id') or self.db.get_meta('cloudflare.zone_id') or '')
        record_id = str(server.get('cf_record_id') or '')
        record_name = str(server.get('cf_dns_name') or '')
        if not zone_id:
            zone_id = self.resolve_zone_id()
        if not record_id and record_name:
            list_data = self._request_json('GET', f'/zones/{zone_id}/dns_records', params={'type': 'A', 'name': record_name})
            if list_data.get('result') or []:
                record_id = list_data['result'][0]['id']
        if not record_id:
            return
        self._request_json('DELETE', f'/zones/{zone_id}/dns_records/{record_id}')
