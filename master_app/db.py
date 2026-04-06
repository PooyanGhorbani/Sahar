from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

from utils import bytes_to_gb


class Database:
    def __init__(self, path: str):
        self.path = path
        self.init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    api_url TEXT NOT NULL,
                    api_token TEXT NOT NULL,
                    public_host TEXT DEFAULT '',
                    host_mode TEXT DEFAULT '',
                    xray_port INTEGER DEFAULT 0,
                    transport_mode TEXT DEFAULT 'tcp',
                    reality_server_name TEXT DEFAULT '',
                    reality_public_key TEXT DEFAULT '',
                    reality_short_id TEXT DEFAULT '',
                    fingerprint TEXT DEFAULT 'chrome',
                    reality_port INTEGER DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_health_status TEXT DEFAULT '',
                    last_health_message TEXT DEFAULT '',
                    last_health_at TEXT DEFAULT '',
                    cpu_percent REAL DEFAULT 0,
                    memory_percent REAL DEFAULT 0,
                    disk_percent REAL DEFAULT 0,
                    load_1m REAL DEFAULT 0,
                    user_count INTEGER DEFAULT 0,
                    xray_active INTEGER DEFAULT 0,
                    last_sync_at TEXT DEFAULT '',
                    cf_zone_id TEXT DEFAULT '',
                    cf_record_id TEXT DEFAULT '',
                    cf_dns_name TEXT DEFAULT '',
                    provisioning_state TEXT DEFAULT 'new',
                    provisioning_message TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    server_id INTEGER NOT NULL,
                    uuid TEXT NOT NULL,
                    traffic_gb INTEGER NOT NULL,
                    used_gb REAL NOT NULL DEFAULT 0,
                    xray_total_bytes INTEGER NOT NULL DEFAULT 0,
                    usage_offset_bytes INTEGER NOT NULL DEFAULT 0,
                    expire_date TEXT NOT NULL,
                    credit_balance INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    plan TEXT NOT NULL DEFAULT '',
                    access_mode TEXT NOT NULL DEFAULT 'all',
                    expiry_warned_at TEXT DEFAULT '',
                    quota_warned_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(server_id) REFERENCES servers(id)
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    actor_chat_id TEXT NOT NULL DEFAULT 'system',
                    actor_role TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_type TEXT NOT NULL,
                    path TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS admins (
                    chat_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS plans (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    traffic_gb INTEGER NOT NULL,
                    days INTEGER NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS user_server_access (
                    user_id INTEGER NOT NULL,
                    server_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, server_id),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS subscription_tokens (
                    user_id INTEGER PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS error_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    component TEXT NOT NULL,
                    target_type TEXT NOT NULL DEFAULT '',
                    target_key TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    trace TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS warning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    level TEXT NOT NULL,
                    warned_at TEXT NOT NULL,
                    UNIQUE(username, kind, level)
                )
                '''
            )
            self._ensure_column(conn, 'users', 'xray_total_bytes', 'INTEGER NOT NULL DEFAULT 0')
            self._ensure_column(conn, 'users', 'usage_offset_bytes', 'INTEGER NOT NULL DEFAULT 0')
            self._ensure_column(conn, 'users', 'expiry_warned_at', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'users', 'access_mode', "TEXT NOT NULL DEFAULT 'all'")
            self._ensure_column(conn, 'users', 'quota_warned_at', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'last_health_status', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'last_health_message', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'last_health_at', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'fingerprint', "TEXT DEFAULT 'chrome'")
            self._ensure_column(conn, 'servers', 'reality_port', 'INTEGER DEFAULT 0')
            self._ensure_column(conn, 'servers', 'cpu_percent', 'REAL DEFAULT 0')
            self._ensure_column(conn, 'servers', 'memory_percent', 'REAL DEFAULT 0')
            self._ensure_column(conn, 'servers', 'disk_percent', 'REAL DEFAULT 0')
            self._ensure_column(conn, 'servers', 'load_1m', 'REAL DEFAULT 0')
            self._ensure_column(conn, 'servers', 'user_count', 'INTEGER DEFAULT 0')
            self._ensure_column(conn, 'servers', 'xray_active', 'INTEGER DEFAULT 0')
            self._ensure_column(conn, 'servers', 'last_sync_at', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'cf_zone_id', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'cf_record_id', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'cf_dns_name', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'servers', 'provisioning_state', "TEXT DEFAULT 'new'")
            self._ensure_column(conn, 'servers', 'provisioning_message', "TEXT DEFAULT ''")
            self._ensure_column(conn, 'audits', 'actor_chat_id', "TEXT NOT NULL DEFAULT 'system'")
            self._ensure_column(conn, 'audits', 'actor_role', "TEXT NOT NULL DEFAULT 'system'")
            self._seed_default_plans(conn)

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        if column not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')

    def _seed_default_plans(self, conn: sqlite3.Connection) -> None:
        count = conn.execute('SELECT COUNT(*) AS c FROM plans').fetchone()['c']
        if int(count) > 0:
            return
        now = '1970-01-01T00:00:00'
        rows = [
            ('starter', '🌱 استارتر — 10GB / 7 روز', 10, 7, 'Starter preset', 1, 10, now, now),
            ('basic', '📦 پایه — 30GB / 30 روز', 30, 30, 'Basic preset', 1, 20, now, now),
            ('plus', '🚀 پلاس — 50GB / 30 روز', 50, 30, 'Plus preset', 1, 30, now, now),
            ('pro', '💎 حرفه‌ای — 100GB / 60 روز', 100, 60, 'Pro preset', 1, 40, now, now),
            ('max', '🏆 مکس — 200GB / 90 روز', 200, 90, 'Max preset', 1, 50, now, now),
            ('unlimited', '♾ نامحدود — 9999GB / 30 روز', 9999, 30, 'Unlimited-like preset', 1, 60, now, now),
        ]
        conn.executemany(
            'INSERT INTO plans (key, label, traffic_gb, days, notes, enabled, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            rows,
        )

    # admins
    def upsert_admin(self, chat_id: str, role: str, display_name: str, created_at: str, updated_at: str, enabled: bool = True) -> None:
        with self.connect() as conn:
            conn.execute(
                '''
                INSERT INTO admins (chat_id, role, display_name, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    role=excluded.role,
                    display_name=excluded.display_name,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                ''',
                (str(chat_id), role, display_name, 1 if enabled else 0, created_at, updated_at),
            )

    def get_admin(self, chat_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM admins WHERE chat_id = ?', (str(chat_id),)).fetchone()
            return dict(row) if row else None

    def list_admins(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            sql = 'SELECT * FROM admins'
            if enabled_only:
                sql += ' WHERE enabled = 1'
            sql += ' ORDER BY CASE role WHEN "owner" THEN 0 WHEN "admin" THEN 1 WHEN "support" THEN 2 ELSE 3 END, chat_id ASC'
            rows = conn.execute(sql).fetchall()
            return [dict(row) for row in rows]

    def set_admin_role(self, chat_id: str, role: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE admins SET role = ?, updated_at = ? WHERE chat_id = ?', (role, updated_at, str(chat_id)))

    def set_admin_enabled(self, chat_id: str, enabled: bool, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE admins SET enabled = ?, updated_at = ? WHERE chat_id = ?', (1 if enabled else 0, updated_at, str(chat_id)))

    def delete_admin(self, chat_id: str) -> None:
        with self.connect() as conn:
            conn.execute('DELETE FROM admins WHERE chat_id = ?', (str(chat_id),))

    def count_admins_by_role(self, role: str) -> int:
        with self.connect() as conn:
            row = conn.execute('SELECT COUNT(*) AS c FROM admins WHERE role = ? AND enabled = 1', (role,)).fetchone()
            return int(row['c'])

    # audits
    def add_audit(self, action: str, target_type: str, target_key: str, details: str, created_at: str, actor_chat_id: str = 'system', actor_role: str = 'system') -> None:
        with self.connect() as conn:
            conn.execute(
                'INSERT INTO audits (action, target_type, target_key, details, actor_chat_id, actor_role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (action, target_type, target_key, details, actor_chat_id, actor_role, created_at),
            )

    def list_audits(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute('SELECT * FROM audits ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
            return [dict(row) for row in rows]


    def add_error_event(self, code: str, component: str, target_type: str, target_key: str, message: str, trace: str, created_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO error_events (code, component, target_type, target_key, message, trace, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (code, component, target_type, target_key, message, trace, created_at),
            )

    def list_error_events(self, limit: int = 20, component: str = '', target_key: str = '') -> List[Dict[str, Any]]:
        with self.connect() as conn:
            sql = 'SELECT * FROM error_events WHERE 1=1'
            params: list[Any] = []
            if component:
                sql += ' AND component = ?'
                params.append(component)
            if target_key:
                sql += ' AND target_key = ?'
                params.append(target_key)
            sql += ' ORDER BY id DESC LIMIT ?'
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    # backups/meta
    def add_backup(self, backup_type: str, path: str, checksum: str, size_bytes: int, created_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                'INSERT INTO backups (backup_type, path, checksum, size_bytes, created_at) VALUES (?, ?, ?, ?, ?)',
                (backup_type, path, checksum, size_bytes, created_at),
            )

    def latest_backup(self) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM backups ORDER BY id DESC LIMIT 1').fetchone()
            return dict(row) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute('INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def get_meta(self, key: str) -> str:
        with self.connect() as conn:
            row = conn.execute('SELECT value FROM meta WHERE key = ?', (key,)).fetchone()
            return row['value'] if row else ''

    # plans
    def list_plans(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            sql = 'SELECT * FROM plans'
            if enabled_only:
                sql += ' WHERE enabled = 1'
            sql += ' ORDER BY sort_order ASC, key ASC'
            rows = conn.execute(sql).fetchall()
            return [dict(row) for row in rows]

    def get_plan(self, key: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM plans WHERE key = ?', (key,)).fetchone()
            return dict(row) if row else None

    def upsert_plan(self, key: str, label: str, traffic_gb: int, days: int, notes: str, enabled: bool, sort_order: int, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                '''
                INSERT INTO plans (key, label, traffic_gb, days, notes, enabled, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    label=excluded.label,
                    traffic_gb=excluded.traffic_gb,
                    days=excluded.days,
                    notes=excluded.notes,
                    enabled=excluded.enabled,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                ''',
                (key, label, traffic_gb, days, notes, 1 if enabled else 0, sort_order, updated_at, updated_at),
            )

    def set_plan_enabled(self, key: str, enabled: bool, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE plans SET enabled = ?, updated_at = ? WHERE key = ?', (1 if enabled else 0, updated_at, key))

    # servers
    def add_or_update_server(self, server: Dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                '''
                INSERT INTO servers (
                    name, api_url, api_token, public_host, host_mode, xray_port,
                    transport_mode, reality_server_name, reality_public_key,
                    reality_short_id, fingerprint, reality_port, enabled, last_health_status,
                    last_health_message, last_health_at, cpu_percent, memory_percent,
                    disk_percent, load_1m, user_count, xray_active, last_sync_at,
                    cf_zone_id, cf_record_id, cf_dns_name, provisioning_state, provisioning_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    api_url=excluded.api_url,
                    api_token=excluded.api_token,
                    public_host=excluded.public_host,
                    host_mode=excluded.host_mode,
                    xray_port=excluded.xray_port,
                    transport_mode=excluded.transport_mode,
                    reality_server_name=excluded.reality_server_name,
                    reality_public_key=excluded.reality_public_key,
                    reality_short_id=excluded.reality_short_id,
                    fingerprint=excluded.fingerprint,
                    reality_port=excluded.reality_port,
                    enabled=excluded.enabled,
                    last_health_status=excluded.last_health_status,
                    last_health_message=excluded.last_health_message,
                    last_health_at=excluded.last_health_at,
                    cpu_percent=excluded.cpu_percent,
                    memory_percent=excluded.memory_percent,
                    disk_percent=excluded.disk_percent,
                    load_1m=excluded.load_1m,
                    user_count=excluded.user_count,
                    xray_active=excluded.xray_active,
                    last_sync_at=excluded.last_sync_at,
                    cf_zone_id=excluded.cf_zone_id,
                    cf_record_id=excluded.cf_record_id,
                    cf_dns_name=excluded.cf_dns_name,
                    provisioning_state=excluded.provisioning_state,
                    provisioning_message=excluded.provisioning_message,
                    updated_at=excluded.updated_at
                ''',
                (
                    server['name'],
                    server.get('api_url', ''),
                    server.get('api_token', ''),
                    server.get('public_host', ''),
                    server.get('host_mode', ''),
                    int(server.get('xray_port') or 0),
                    server.get('transport_mode', 'tcp'),
                    server.get('reality_server_name', ''),
                    server.get('reality_public_key', ''),
                    server.get('reality_short_id', ''),
                    server.get('fingerprint', 'chrome'),
                    int(server.get('reality_port') or 0),
                    1 if server.get('enabled', True) else 0,
                    server.get('last_health_status', ''),
                    server.get('last_health_message', ''),
                    server.get('last_health_at', ''),
                    float(server.get('cpu_percent') or 0),
                    float(server.get('memory_percent') or 0),
                    float(server.get('disk_percent') or 0),
                    float(server.get('load_1m') or 0),
                    int(server.get('user_count') or 0),
                    1 if server.get('xray_active') else 0,
                    server.get('last_sync_at', ''),
                    server.get('cf_zone_id', ''),
                    server.get('cf_record_id', ''),
                    server.get('cf_dns_name', ''),
                    server.get('provisioning_state', 'healthy'),
                    server.get('provisioning_message', ''),
                    server.get('created_at', ''),
                    server.get('updated_at', ''),
                ),
            )

    def update_server_health(self, name: str, status: str, message: str, checked_at: str, metrics: Optional[Dict[str, Any]] = None) -> None:
        metrics = metrics or {}
        with self.connect() as conn:
            conn.execute(
                '''
                UPDATE servers
                SET last_health_status = ?, last_health_message = ?, last_health_at = ?, updated_at = ?,
                    provisioning_state = CASE WHEN ? = 'ok' THEN 'healthy' ELSE provisioning_state END,
                    provisioning_message = CASE WHEN ? = 'ok' THEN provisioning_message ELSE ? END,
                    cpu_percent = COALESCE(?, cpu_percent),
                    memory_percent = COALESCE(?, memory_percent),
                    disk_percent = COALESCE(?, disk_percent),
                    load_1m = COALESCE(?, load_1m),
                    user_count = COALESCE(?, user_count),
                    xray_active = COALESCE(?, xray_active)
                WHERE name = ?
                ''',
                (
                    status,
                    message,
                    checked_at,
                    checked_at,
                    status,
                    status,
                    message,
                    metrics.get('cpu_percent'),
                    metrics.get('memory_percent'),
                    metrics.get('disk_percent'),
                    metrics.get('load_1m'),
                    metrics.get('user_count'),
                    1 if metrics.get('xray_active') else 0 if 'xray_active' in metrics else None,
                    name,
                ),
            )


    def update_server_stage(self, name: str, provisioning_state: str, provisioning_message: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
            'UPDATE servers SET provisioning_state = ?, provisioning_message = ?, updated_at = ? WHERE name = ?',
            (provisioning_state, provisioning_message, updated_at, name),
            )

    def mark_server_sync(self, name: str, synced_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE servers SET last_sync_at = ?, updated_at = ? WHERE name = ?', (synced_at, synced_at, name))

    def update_server_dns(self, name: str, zone_id: str, record_id: str, dns_name: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE servers SET cf_zone_id = ?, cf_record_id = ?, cf_dns_name = ?, public_host = ?, host_mode = ?, updated_at = ? WHERE name = ?', (zone_id, record_id, dns_name, dns_name, 'domain', updated_at, name))

    def get_server(self, name: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM servers WHERE name = ?', (name,)).fetchone()
            return dict(row) if row else None

    def get_server_by_id(self, server_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM servers WHERE id = ?', (server_id,)).fetchone()
            return dict(row) if row else None

    def list_servers(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            sql = 'SELECT * FROM servers'
            if enabled_only:
                sql += ' WHERE enabled = 1'
            sql += ' ORDER BY name ASC'
            rows = conn.execute(sql).fetchall()
            return [dict(row) for row in rows]

    def set_server_enabled(self, name: str, enabled: bool, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE servers SET enabled = ?, updated_at = ? WHERE name = ?', (1 if enabled else 0, updated_at, name))

    def delete_server(self, name: str) -> None:
        with self.connect() as conn:
            conn.execute('DELETE FROM servers WHERE name = ?', (name,))

    def count_users_for_server(self, server_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                '''
                SELECT COUNT(DISTINCT u.id) AS c
                FROM users u
                LEFT JOIN user_server_access usa ON usa.user_id = u.id
                WHERE u.server_id = ?
                   OR u.access_mode = 'all'
                   OR usa.server_id = ?
                ''',
                (server_id, server_id),
            ).fetchone()
            return int(row['c'])

    def list_primary_users_for_server(self, server_id: int) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                '''
                SELECT u.*, s.name AS server_name
                FROM users u JOIN servers s ON s.id = u.server_id
                WHERE u.server_id = ?
                ORDER BY u.username ASC
                ''',
                (server_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    # users


    def add_or_update_user(self, username: str, server_id: int, uuid_value: str, traffic_gb: int, expire_date: str, notes: str, plan: str, created_at: str, updated_at: str) -> None:
        existing = self.get_user(username)
        if existing:
            with self.connect() as conn:
                conn.execute(
                    "UPDATE users SET server_id = ?, uuid = ?, traffic_gb = ?, expire_date = ?, notes = ?, plan = ?, updated_at = ? WHERE username = ?",
                    (server_id, uuid_value, traffic_gb, expire_date, notes, plan, updated_at, username),
                )
            return
        self.add_user(username, server_id, uuid_value, traffic_gb, expire_date, notes, plan, created_at, updated_at)
    def add_user(self, username: str, server_id: int, uuid_value: str, traffic_gb: int, expire_date: str, notes: str, plan: str, created_at: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                '''
                INSERT INTO users (
                    username, server_id, uuid, traffic_gb, used_gb, xray_total_bytes,
                    usage_offset_bytes, expire_date, credit_balance, is_active,
                    notes, plan, access_mode, expiry_warned_at, quota_warned_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, 0, ?, 0, 1, ?, ?, 'all', '', '', ?, ?)
                ''',
                (username, server_id, uuid_value, traffic_gb, expire_date, notes, plan, created_at, updated_at),
            )

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                '''
                SELECT u.*, s.name AS server_name, s.public_host, s.host_mode, s.xray_port,
                       s.transport_mode, s.reality_server_name, s.reality_public_key,
                       s.reality_short_id, s.fingerprint, s.reality_port
                FROM users u
                JOIN servers s ON s.id = u.server_id
                WHERE u.username = ?
                ''',
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def list_users(self, server_name: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if server_name:
                rows = conn.execute(
                    '''
                    SELECT DISTINCT u.*, s.name AS server_name
                    FROM users u
                    JOIN servers s ON s.id = u.server_id
                    LEFT JOIN user_server_access usa ON usa.user_id = u.id
                    LEFT JOIN servers sa ON sa.id = usa.server_id
                    WHERE s.name = ?
                       OR u.access_mode = 'all'
                       OR sa.name = ?
                    ORDER BY u.created_at DESC
                    ''',
                    (server_name, server_name),
                ).fetchall()
            else:
                rows = conn.execute(
                    '''
                    SELECT u.*, s.name AS server_name
                    FROM users u JOIN servers s ON s.id = u.server_id
                    ORDER BY u.created_at DESC
                    '''
                ).fetchall()
            return [dict(row) for row in rows]

    def search_users(self, pattern: str) -> List[Dict[str, Any]]:
        like = f'%{pattern}%'
        with self.connect() as conn:
            rows = conn.execute(
                '''
                SELECT u.*, s.name AS server_name
                FROM users u JOIN servers s ON s.id = u.server_id
                WHERE u.username LIKE ? OR u.plan LIKE ? OR u.notes LIKE ?
                ORDER BY u.username ASC
                LIMIT 100
                ''',
                (like, like, like),
            ).fetchall()
            return [dict(row) for row in rows]

    def sync_user_total_bytes(self, username: str, total_bytes: int, updated_at: str) -> None:
        with self.connect() as conn:
            row = conn.execute('SELECT usage_offset_bytes FROM users WHERE username = ?', (username,)).fetchone()
            if not row:
                return
            offset = int(row['usage_offset_bytes'] or 0)
            used_bytes = max(total_bytes - offset, 0)
            conn.execute('UPDATE users SET xray_total_bytes = ?, used_gb = ?, updated_at = ? WHERE username = ?', (int(total_bytes), bytes_to_gb(used_bytes), updated_at, username))

    def reset_user_usage_baseline(self, username: str, updated_at: str) -> None:
        with self.connect() as conn:
            row = conn.execute('SELECT xray_total_bytes FROM users WHERE username = ?', (username,)).fetchone()
            if not row:
                return
            total = int(row['xray_total_bytes'] or 0)
            conn.execute("UPDATE users SET usage_offset_bytes = ?, used_gb = 0, quota_warned_at = '', updated_at = ? WHERE username = ?", (total, updated_at, username))

    def set_expire(self, username: str, expire_date: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET expire_date = ?, expiry_warned_at = '', updated_at = ? WHERE username = ?", (expire_date, updated_at, username))

    def set_traffic(self, username: str, traffic_gb: int, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET traffic_gb = ?, quota_warned_at = '', updated_at = ? WHERE username = ?", (traffic_gb, updated_at, username))

    def add_traffic(self, username: str, traffic_gb: int, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET traffic_gb = traffic_gb + ?, quota_warned_at = '', updated_at = ? WHERE username = ?", (traffic_gb, updated_at, username))

    def add_credit(self, username: str, amount: int, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE users SET credit_balance = credit_balance + ?, updated_at = ? WHERE username = ?', (amount, updated_at, username))

    def take_credit(self, username: str, amount: int, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE users SET credit_balance = credit_balance - ?, updated_at = ? WHERE username = ? AND credit_balance >= ?', (amount, updated_at, username, amount))

    def set_active(self, username: str, active: bool, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE users SET is_active = ?, updated_at = ? WHERE username = ?', (1 if active else 0, updated_at, username))

    def set_server_for_user(self, username: str, server_id: int, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE users SET server_id = ?, usage_offset_bytes = 0, xray_total_bytes = 0, used_gb = 0, quota_warned_at = '', updated_at = ? WHERE username = ?", (server_id, updated_at, username))

    def update_user_notes(self, username: str, notes: str, plan: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE users SET notes = ?, plan = ?, updated_at = ? WHERE username = ?', (notes, plan, updated_at, username))

    def delete_user(self, username: str) -> None:
        with self.connect() as conn:
            conn.execute('DELETE FROM users WHERE username = ?', (username,))

    def list_expired_active_users(self, today_str: str) -> List[Dict[str, Any]]:
        return self._users_with_server('WHERE u.is_active = 1 AND u.expire_date < ? ORDER BY u.expire_date ASC', (today_str,))

    def list_over_quota_active_users(self) -> List[Dict[str, Any]]:
        return self._users_with_server('WHERE u.is_active = 1 AND u.used_gb >= u.traffic_gb ORDER BY u.updated_at DESC', ())

    def list_expiring_soon(self, today_str: str, cutoff_str: str) -> List[Dict[str, Any]]:
        return self._users_with_server('WHERE u.is_active = 1 AND u.expire_date >= ? AND u.expire_date <= ? ORDER BY u.expire_date ASC', (today_str, cutoff_str))

    def list_quota_reached_threshold(self, usage_percent: int) -> List[Dict[str, Any]]:
        threshold = float(usage_percent) / 100.0
        with self.connect() as conn:
            rows = conn.execute(
                '''
                SELECT u.*, s.name AS server_name, s.api_url, s.api_token, s.public_host, s.host_mode,
                       s.xray_port, s.transport_mode, s.reality_server_name, s.reality_public_key,
                       s.reality_short_id, s.fingerprint, s.reality_port
                FROM users u
                JOIN servers s ON s.id = u.server_id
                WHERE u.is_active = 1 AND u.traffic_gb > 0
                  AND u.used_gb >= (u.traffic_gb * ?)
                  AND u.used_gb < u.traffic_gb
                ORDER BY u.used_gb DESC
                ''',
                (threshold,),
            ).fetchall()
            return [dict(row) for row in rows]

    # warnings
    def warning_sent(self, username: str, kind: str, level: str) -> bool:
        with self.connect() as conn:
            row = conn.execute('SELECT 1 FROM warning_events WHERE username = ? AND kind = ? AND level = ? LIMIT 1', (username, kind, level)).fetchone()
            return bool(row)

    def mark_warning_sent(self, username: str, kind: str, level: str, warned_at: str) -> None:
        with self.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO warning_events (username, kind, level, warned_at) VALUES (?, ?, ?, ?)', (username, kind, level, warned_at))

    def list_users_by_access_mode(self, access_mode: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT u.*, s.name AS server_name
                FROM users u JOIN servers s ON s.id = u.server_id
                WHERE u.access_mode = ?
                ORDER BY u.username ASC
                """,
                (access_mode,),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_user_access_mode(self, username: str, access_mode: str, updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE users SET access_mode = ?, updated_at = ? WHERE username = ?', (access_mode, updated_at, username))

    def clear_user_server_access(self, username: str) -> None:
        with self.connect() as conn:
            conn.execute('DELETE FROM user_server_access WHERE user_id = (SELECT id FROM users WHERE username = ?)', (username,))

    def grant_user_server_access(self, username: str, server_name: str, updated_at: str) -> None:
        with self.connect() as conn:
            user = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            server = conn.execute('SELECT id FROM servers WHERE name = ?', (server_name,)).fetchone()
            if not user or not server:
                return
            conn.execute(
                'INSERT OR REPLACE INTO user_server_access (user_id, server_id, created_at, updated_at) VALUES (?, ?, ?, ?)',
                (int(user['id']), int(server['id']), updated_at, updated_at),
            )

    def revoke_user_server_access(self, username: str, server_name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                'DELETE FROM user_server_access WHERE user_id = (SELECT id FROM users WHERE username = ?) AND server_id = (SELECT id FROM servers WHERE name = ?)',
                (username, server_name),
            )

    def list_user_access_servers(self, username: str, enabled_only: bool = True) -> List[Dict[str, Any]]:
        user = self.get_user(username)
        if not user:
            return []
        if user.get('access_mode') == 'all':
            return self.list_servers(enabled_only=enabled_only)
        with self.connect() as conn:
            sql = """
                SELECT s.*
                FROM user_server_access usa
                JOIN users u ON u.id = usa.user_id
                JOIN servers s ON s.id = usa.server_id
                WHERE u.username = ?
            """
            params = [username]
            if enabled_only:
                sql += ' AND s.enabled = 1'
            sql += ' ORDER BY s.name ASC'
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def list_user_access_server_names(self, username: str, enabled_only: bool = True) -> List[str]:
        return [row['name'] for row in self.list_user_access_servers(username, enabled_only=enabled_only)]

    def ensure_subscription_token(self, username: str, token_value: str, updated_at: str) -> str:
        with self.connect() as conn:
            user = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if not user:
                raise ValueError('user not found')
            row = conn.execute('SELECT token FROM subscription_tokens WHERE user_id = ?', (int(user['id']),)).fetchone()
            if row:
                return str(row['token'])
            conn.execute(
                'INSERT INTO subscription_tokens (user_id, token, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)',
                (int(user['id']), token_value, updated_at, updated_at),
            )
            return token_value

    def get_subscription_token(self, username: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                'SELECT st.token FROM subscription_tokens st JOIN users u ON u.id = st.user_id WHERE u.username = ? AND st.enabled = 1',
                (username,),
            ).fetchone()
            return row['token'] if row else ''

    def get_user_by_subscription_token(self, token: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT u.*, s.name AS server_name, s.public_host, s.host_mode, s.xray_port,
                       s.transport_mode, s.reality_server_name, s.reality_public_key,
                       s.reality_short_id, s.fingerprint, s.reality_port
                FROM subscription_tokens st
                JOIN users u ON u.id = st.user_id
                JOIN servers s ON s.id = u.server_id
                WHERE st.token = ? AND st.enabled = 1
                """,
                (token,),
            ).fetchone()
            return dict(row) if row else None

    def _users_with_server(self, where_clause: str, params: Iterable[Any]) -> List[Dict[str, Any]]:
        sql = f'''
            SELECT u.*, s.name AS server_name, s.api_url, s.api_token, s.public_host, s.host_mode,
                   s.xray_port, s.transport_mode, s.reality_server_name, s.reality_public_key,
                   s.reality_short_id, s.fingerprint, s.reality_port
            FROM users u
            JOIN servers s ON s.id = u.server_id
            {where_clause}
        '''
        with self.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]
