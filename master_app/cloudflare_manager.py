from __future__ import annotations

import ipaddress
import logging
import re
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
        self._refresh_flags()
        key = str(config.get('cloudflare_token_encryption_key') or '')
        self._fernet = Fernet(key.encode()) if key else None
        self.base = 'https://api.cloudflare.com/client/v4'
        self.timeout = int(config.get('cloudflare_timeout_seconds', 30))

    def _refresh_flags(self) -> None:
        domain = str(self.config.get('cloudflare_domain_name') or self.config.get('cloudflare_zone_name') or '').strip()
        self.enabled = bool(self.config.get('cloudflare_enabled')) and bool(domain)
        self.tunnel_enabled = bool(self.config.get('cloudflare_tunnel_enabled')) and self.enabled

    def reload(self, config: Dict[str, Any]) -> None:
        self.config = config
        self._refresh_flags()

    def clear_cached_ids(self) -> None:
        self.db.delete_meta('cloudflare.zone_id')
        self.db.delete_meta('cloudflare.account_id')

    def store_token(self, token: str) -> None:
        if not self._fernet:
            raise CloudflareError('cloudflare encryption key missing')
        self.db.set_meta('cloudflare.token.enc', self._fernet.encrypt(token.encode()).decode())
        self.clear_cached_ids()

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
        account_id = str((result[0].get('account') or {}).get('id') or '')
        if account_id:
            self.db.set_meta('cloudflare.account_id', account_id)
        return zone_id

    def resolve_account_id(self) -> str:
        cached = self.db.get_meta('cloudflare.account_id')
        if cached:
            return cached
        zone_id = self.resolve_zone_id()
        zone = self._request_json('GET', f'/zones/{zone_id}').get('result') or {}
        account_id = str((zone.get('account') or {}).get('id') or '')
        if not account_id:
            raise CloudflareError('could not resolve Cloudflare account id from zone')
        self.db.set_meta('cloudflare.account_id', account_id)
        return account_id

    def test_connection(self) -> Dict[str, str]:
        zone_id = self.resolve_zone_id()
        account_id = self.resolve_account_id()
        return {
            'zone_id': zone_id,
            'account_id': account_id,
            'domain': self.configured_domain_name(),
            'token': 'configured' if self.get_token() else 'missing',
        }

    def _sanitize_label(self, value: str) -> str:
        label = re.sub(r'[^a-zA-Z0-9-]+', '-', str(value or '').strip().lower())
        label = re.sub(r'-{2,}', '-', label).strip('-')
        return label or 'node'

    def desired_hostname(self, server_name: str) -> str:
        zone = self.configured_domain_name()
        base = str(self.config.get('cloudflare_base_subdomain') or '').strip().strip('.')
        label = self._sanitize_label(server_name)
        if base:
            return f'{label}.{base}.{zone}'
        return f'{label}.{zone}'

    def _record_name(self, server_name: str) -> str:
        return self.desired_hostname(server_name)

    def ensure_server_dns(self, server_name: str, target_value: str, record_type: str = 'A') -> Dict[str, str]:
        record_type = record_type.upper().strip()
        if record_type in {'A', 'AAAA'}:
            try:
                ipaddress.ip_address(target_value)
            except ValueError as exc:
                raise CloudflareError(f'invalid IP for DNS record: {target_value}') from exc
        elif record_type != 'CNAME':
            raise CloudflareError(f'unsupported DNS record type: {record_type}')
        zone_id = self.resolve_zone_id()
        record_name = self._record_name(server_name)
        payload: Dict[str, Any] = {'type': record_type, 'name': record_name, 'content': target_value, 'ttl': 1}
        if record_type != 'CNAME' or self.config.get('cloudflare_dns_proxied'):
            payload['proxied'] = bool(self.config.get('cloudflare_dns_proxied', False))
        list_data = self._request_json('GET', f'/zones/{zone_id}/dns_records', params={'name': record_name})
        rows = [row for row in (list_data.get('result') or []) if str(row.get('type', '')).upper() == record_type]
        if rows:
            record_id = rows[0]['id']
            data = self._request_json('PUT', f'/zones/{zone_id}/dns_records/{record_id}', payload=payload)
            rec = data['result']
        else:
            data = self._request_json('POST', f'/zones/{zone_id}/dns_records', payload=payload)
            rec = data['result']
        return {'zone_id': zone_id, 'record_id': rec['id'], 'dns_name': rec['name'], 'record_type': record_type}

    def _list_tunnels(self, account_id: str, name: str) -> list[dict]:
        data = self._request_json('GET', f'/accounts/{account_id}/cfd_tunnel', params={'name': name, 'is_deleted': 'false'})
        return data.get('result') or []

    def _create_remote_tunnel(self, account_id: str, name: str) -> Dict[str, Any]:
        data = self._request_json('POST', f'/accounts/{account_id}/cfd_tunnel', payload={'name': name, 'config_src': 'cloudflare'})
        return data.get('result') or {}

    def ensure_remote_tunnel(self, server_name: str, local_service_url: str, existing: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        if not self.tunnel_enabled:
            raise CloudflareError('cloudflare tunnel mode is disabled')
        account_id = self.resolve_account_id()
        desired_name = f'sahar-{self._sanitize_label(server_name)}'
        existing = existing or {}
        tunnel_id = str(existing.get('cf_tunnel_id') or '')
        tunnel_name = str(existing.get('cf_tunnel_name') or desired_name)
        tunnel_token = ''
        if tunnel_id:
            tunnel = self._request_json('GET', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}').get('result') or {}
            tunnel_name = str(tunnel.get('name') or tunnel_name)
            tunnel_token = str(tunnel.get('token') or '')
        else:
            tunnels = self._list_tunnels(account_id, desired_name)
            tunnel = tunnels[0] if tunnels else self._create_remote_tunnel(account_id, desired_name)
            tunnel_id = str(tunnel.get('id') or '')
            tunnel_name = str(tunnel.get('name') or desired_name)
            tunnel_token = str(tunnel.get('token') or '')
        if not tunnel_id:
            raise CloudflareError('failed to obtain Cloudflare tunnel id')
        if not tunnel_token:
            token_data = self._request_json('GET', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token')
            tunnel_token = str((token_data.get('result') or {}).get('token') or token_data.get('result') or '')
        hostname = self.desired_hostname(server_name)
        payload = {
            'config': {
                'ingress': [
                    {
                        'hostname': hostname,
                        'service': local_service_url,
                        'originRequest': {},
                    },
                    {'service': 'http_status:404'},
                ]
            }
        }
        self._request_json('PUT', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations', payload=payload)
        dns = self.ensure_server_dns(server_name, f'{tunnel_id}.cfargotunnel.com', record_type='CNAME')
        return {
            'account_id': account_id,
            'tunnel_id': tunnel_id,
            'tunnel_name': tunnel_name,
            'tunnel_token': tunnel_token,
            'dns_name': dns['dns_name'],
            'zone_id': dns['zone_id'],
            'record_id': dns['record_id'],
            'record_type': dns['record_type'],
        }

    def delete_tunnel(self, tunnel_id: str) -> None:
        if not tunnel_id:
            return
        account_id = self.resolve_account_id()
        self._request_json('DELETE', f'/accounts/{account_id}/cfd_tunnel/{tunnel_id}')

    def delete_server_dns(self, server: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        zone_id = str(server.get('cf_zone_id') or self.db.get_meta('cloudflare.zone_id') or '')
        record_id = str(server.get('cf_record_id') or '')
        record_name = str(server.get('cf_dns_name') or '')
        record_type = str(server.get('cf_record_type') or '')
        if not zone_id:
            zone_id = self.resolve_zone_id()
        if not record_id and record_name:
            params = {'name': record_name}
            if record_type:
                params['type'] = record_type
            list_data = self._request_json('GET', f'/zones/{zone_id}/dns_records', params=params)
            if list_data.get('result') or []:
                record_id = list_data['result'][0]['id']
        if record_id:
            self._request_json('DELETE', f'/zones/{zone_id}/dns_records/{record_id}')
