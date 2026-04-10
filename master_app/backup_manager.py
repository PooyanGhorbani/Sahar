from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, Iterable

from agent_client import AgentClient
from utils import ensure_dir, now_iso, sha256_file


class BackupManager:
    def __init__(self, config: Dict, db):
        self.config = config
        self.db = db
        self.backup_dir = config['backup_dir']
        ensure_dir(self.backup_dir)

    def _backup_name(self, prefix: str = 'sahar-master') -> str:
        stamp = now_iso().replace(':', '-').replace('.', '-')
        return f'{prefix}-{stamp}.tar.gz'

    def create_backup(self, servers: Iterable[Dict]) -> Dict[str, str]:
        backup_name = self._backup_name('sahar-master-full')
        final_path = os.path.join(self.backup_dir, backup_name)
        with tempfile.TemporaryDirectory(prefix='sahar_backup_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._copy_master_state(tmp_root)
            self._collect_agent_backups(tmp_root, servers)
            with tarfile.open(final_path, 'w:gz') as tar:
                tar.add(tmp_root, arcname='sahar-backup')
        checksum = sha256_file(final_path)
        size_bytes = os.path.getsize(final_path)
        self.db.add_backup('master_bundle', final_path, checksum, size_bytes, now_iso())
        self.prune_old_backups(int(self.config.get('backup_retention', 10)))
        return {'path': final_path, 'checksum': checksum, 'size_bytes': size_bytes}

    def create_quick_snapshot(self, label: str = 'prechange') -> Dict[str, str]:
        snapshot_dir = os.path.join(self.backup_dir, 'snapshots')
        ensure_dir(snapshot_dir)
        final_path = os.path.join(snapshot_dir, self._backup_name(f'sahar-{label}'))
        with tempfile.TemporaryDirectory(prefix='sahar_snapshot_') as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._copy_master_state(tmp_root)
            with tarfile.open(final_path, 'w:gz') as tar:
                tar.add(tmp_root, arcname='sahar-snapshot')
        checksum = sha256_file(final_path)
        size_bytes = os.path.getsize(final_path)
        self.db.add_backup('quick_snapshot', final_path, checksum, size_bytes, now_iso())
        self.prune_snapshot_backups(int(self.config.get('quick_snapshot_retention', 20)))
        return {'path': final_path, 'checksum': checksum, 'size_bytes': size_bytes}

    def _copy_master_state(self, tmp_root: Path) -> None:
        state_dir = tmp_root / 'master'
        state_dir.mkdir(parents=True, exist_ok=True)
        for key in ('database_path', 'log_path'):
            path = self.config.get(key)
            if path and os.path.exists(path):
                shutil.copy2(path, state_dir / os.path.basename(path))
        config_path = os.path.expandvars(os.environ.get('SAHAR_CONFIG', ''))
        if config_path and os.path.exists(config_path):
            shutil.copy2(config_path, state_dir / 'config.json')
        qr_dir = self.config.get('qr_dir')
        if qr_dir and os.path.isdir(qr_dir):
            shutil.copytree(qr_dir, state_dir / 'qrcodes', dirs_exist_ok=True)

    def _collect_agent_backups(self, tmp_root: Path, servers: Iterable[Dict]) -> None:
        agents_dir = tmp_root / 'agents'
        agents_dir.mkdir(parents=True, exist_ok=True)
        for server in servers:
            server_dir = agents_dir / server['name']
            server_dir.mkdir(parents=True, exist_ok=True)
            client = AgentClient(server['api_url'], server['api_token'], timeout=int(self.config.get('agent_timeout_seconds', 15)), tls_fingerprint=server.get('api_tls_fingerprint', ''))
            try:
                meta = client.create_backup()['data']
                filename = meta['filename']
                client.download_backup(filename, str(server_dir / filename))
            except Exception as exc:
                (server_dir / 'ERROR.txt').write_text(f'backup failed: {exc}\n', encoding='utf-8')

    def prune_old_backups(self, keep: int) -> None:
        backups = sorted(Path(self.backup_dir).glob('*.tar.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in backups[keep:]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def prune_snapshot_backups(self, keep: int) -> None:
        snapshots_dir = Path(self.backup_dir) / 'snapshots'
        if not snapshots_dir.exists():
            return
        backups = sorted(snapshots_dir.glob('*.tar.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in backups[keep:]:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
