from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class AgentError(Exception):
    pass


@dataclass
class AgentClient:
    base_url: str
    token: str
    timeout: int = 15
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self):
        self.base_url = self.base_url.rstrip('/')
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=['GET', 'POST'],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({'X-Agent-Token': self.token})

    def _handle_response(self, resp: requests.Response) -> Dict[str, Any]:
        try:
            data = resp.json()
        except Exception as exc:
            raise AgentError(f'invalid agent response ({resp.status_code}): {exc}') from exc
        if not resp.ok or not data.get('ok'):
            message = data.get('error') or f'agent request failed ({resp.status_code})'
            raise AgentError(message)
        return data

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = self.session.get(f'{self.base_url}{path}', params=params, timeout=self.timeout)
        return self._handle_response(resp)

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        resp = self.session.post(f'{self.base_url}{path}', json=payload, timeout=self.timeout)
        return self._handle_response(resp)

    def download(self, path: str, dest_path: str) -> str:
        with self.session.get(f'{self.base_url}{path}', timeout=max(self.timeout, 60), stream=True) as resp:
            if not resp.ok:
                raise AgentError(f'download failed ({resp.status_code})')
            with open(dest_path, 'wb') as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
        return dest_path

    def health(self) -> Dict[str, Any]:
        return self.get('/health')

    def add_user(self, username: str, uuid_value: str) -> Dict[str, Any]:
        return self.post('/users/add', {'username': username, 'uuid': uuid_value})

    def remove_user(self, username: str) -> Dict[str, Any]:
        return self.post('/users/remove', {'username': username})

    def disable_user(self, username: str) -> Dict[str, Any]:
        return self.post('/users/disable', {'username': username})

    def enable_user(self, username: str, uuid_value: str) -> Dict[str, Any]:
        return self.post('/users/enable', {'username': username, 'uuid': uuid_value})

    def get_user_stats(self, username: str) -> Dict[str, Any]:
        return self.get('/users/stats', params={'username': username})

    def all_user_stats(self) -> Dict[str, Any]:
        return self.get('/users/all-stats')

    def list_users(self) -> Dict[str, Any]:
        return self.get('/users/list')

    def create_backup(self) -> Dict[str, Any]:
        return self.post('/backup/create', {})

    def download_backup(self, filename: str, dest_path: str) -> str:
        return self.download(f'/backup/download/{filename}', dest_path)

    def profiles(self) -> Dict[str, Any]:
        return self.get('/profiles')
