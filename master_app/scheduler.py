from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime, timedelta

from agent_client import AgentClient
from backup_manager import BackupManager
from cloudflare_manager import CloudflareManager
from cloudflared_runtime import CloudflaredRuntimeError, deploy_local_service
from db import Database
from error_tools import record_error
from notifier import Notifier
from utils import date_after_days, load_config, now_iso, setup_logging, today_utc

CONFIG_PATH = os.path.expandvars(os.environ.get('SAHAR_CONFIG', '/opt/sahar-master/data/config.json'))
CONFIG = load_config(CONFIG_PATH)
setup_logging(CONFIG['log_path'])
LOGGER = logging.getLogger('scheduler')
DB = Database(CONFIG['database_path'])
NOTIFIER = Notifier(CONFIG['bot_token'], CONFIG['admin_ids'])
CLOUDFLARE = CloudflareManager(CONFIG, DB)

SERVER_STATUS_ALERTS = bool(CONFIG.get('notify_on_server_status_change', True))
CLOUDFLARE_AUTO_SYNC = bool(CONFIG.get('cloudflare_auto_sync_enabled', True))
CLOUDFLARE_AUTO_SYNC_MINUTES = int(CONFIG.get('cloudflare_auto_sync_interval_minutes', 30) or 30)


def _server_summary_for_user(username: str) -> str:
    names = DB.list_user_access_server_names(username, enabled_only=False)
    if not names:
        return 'بدون سرور'
    if len(names) <= 3:
        return ', '.join(names)
    return f"{', '.join(names[:3])} (+{len(names)-3})"
BACKUPS = BackupManager(CONFIG, DB)
INTERVAL_SECONDS = int(CONFIG.get('scheduler_interval_seconds', 300))
AGENT_TIMEOUT = int(CONFIG.get('agent_timeout_seconds', 15))
WARN_DAYS_LEFT = int(CONFIG.get('warn_days_left', 3))
WARN_USAGE_PERCENT = int(CONFIG.get('warn_usage_percent', 80))
BACKUP_INTERVAL_HOURS = int(CONFIG.get('backup_interval_hours', 24))
def _parse_int_schedule(value, default_csv: str):
    if isinstance(value, (list, tuple)):
        return [int(x) for x in value]
    raw = str(value if value is not None else default_csv)
    return [int(x.strip()) for x in raw.split(',') if str(x).strip()]


WARN_DAYS_SCHEDULE = _parse_int_schedule(CONFIG.get('warn_days_schedule', '7,3,1'), '7,3,1')
WARN_USAGE_SCHEDULE = _parse_int_schedule(CONFIG.get('warn_usage_schedule', '80,95'), '80,95')


def server_client(server):
    return AgentClient(server['api_url'], server['api_token'], timeout=AGENT_TIMEOUT, tls_fingerprint=server.get('api_tls_fingerprint', ''))


def accessible_servers_for_user(user: dict) -> list[dict]:
    return DB.list_user_access_servers(user['username'], enabled_only=True)



def _notify_server_status_change(server: dict, old_status: str, new_status: str, message: str = '') -> None:
    if not SERVER_STATUS_ALERTS or old_status == new_status:
        return
    if new_status not in {'ok', 'down'}:
        return
    if not old_status:
        return
    if new_status == 'down':
        text = (
            f"🚨 سرور از دسترس خارج شد\n"
            f"نام: {server['name']}\n"
            f"وضعیت قبلی: {old_status} → {new_status}\n"
            f"پیام: {message or '-'}"
        )
    else:
        text = (
            f"✅ سرور دوباره آنلاین شد\n"
            f"نام: {server['name']}\n"
            f"وضعیت قبلی: {old_status} → {new_status}"
        )
    try:
        NOTIFIER.message(text)
    except Exception as exc:
        LOGGER.warning('server_status_notify_failed server=%s error=%s', server.get('name'), exc)


def _resolve_target_ip_for_dns(host: str) -> str:
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        try:
            return socket.gethostbyname(host)
        except OSError as exc:
            raise RuntimeError(f'failed to resolve host for DNS: {host}') from exc


def _is_local_server(server: dict) -> bool:
    api_url = str(server.get('api_url') or '')
    if server.get('name') == CONFIG.get('local_server_name'):
        return True
    return api_url.startswith('http://127.0.0.1:') or api_url.startswith('http://localhost:')


def _cloudflare_service_url_for_server(server: dict) -> str:
    xray_port = int(server.get('xray_port') or 0)
    if xray_port <= 0:
        raise RuntimeError(f"server {server.get('name')} does not have a valid xray port")
    return f'http://127.0.0.1:{xray_port}'


def sync_cloudflare_if_needed() -> tuple[int, list[str]]:
    if not getattr(CLOUDFLARE, 'enabled', False) or not CLOUDFLARE_AUTO_SYNC:
        return 0, []
    last = DB.get_meta('last_cloudflare_sync_at')
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if datetime.utcnow() - last_dt < timedelta(minutes=CLOUDFLARE_AUTO_SYNC_MINUTES):
                return 0, []
        except ValueError:
            pass
    synced: list[str] = []
    for server in DB.list_servers(enabled_only=True):
        try:
            if getattr(CLOUDFLARE, 'tunnel_enabled', False):
                if not (_is_local_server(server) or server.get('cf_tunnel_id')):
                    DB.update_server_tunnel(server['name'], str(server.get('cf_tunnel_id') or ''), str(server.get('cf_tunnel_name') or ''), 'needs_provision', now_iso())
                    raise RuntimeError(f"server {server.get('name')} is not tunnel-ready; add it with SSH provisioning or configure cloudflared on the server first")
                info = CLOUDFLARE.ensure_remote_tunnel(server['name'], _cloudflare_service_url_for_server(server), existing=server)
                tunnel_status = 'configured'
                if _is_local_server(server):
                    try:
                        deploy_local_service(info['tunnel_token'])
                    except CloudflaredRuntimeError as exc:
                        tunnel_status = 'pending_runtime'
                        LOGGER.warning('cloudflared_runtime_pending server=%s error=%s', server.get('name'), exc)
                DB.update_server_tunnel(server['name'], info['tunnel_id'], info['tunnel_name'], tunnel_status, now_iso())
                DB.update_server_dns(server['name'], info['zone_id'], info['record_id'], info['dns_name'], now_iso(), info.get('record_type', ''))
                synced.append(info['dns_name'])
                continue
            target = str(server.get('public_host') or '').strip()
            if not target:
                continue
            info = CLOUDFLARE.ensure_server_dns(server['name'], _resolve_target_ip_for_dns(target))
            DB.update_server_dns(server['name'], info['zone_id'], info['record_id'], info['dns_name'], now_iso(), info.get('record_type', ''))
            synced.append(info['dns_name'])
        except (CloudflaredRuntimeError, Exception) as exc:
            record_error(DB, LOGGER, component='cloudflare', target_type='server', target_key=server.get('name', ''), message='automatic cloudflare sync failed', exc=exc)
    DB.set_meta('last_cloudflare_sync_at', now_iso())
    return len(synced), synced


def refresh_health_cache() -> int:
    count = 0
    for server in DB.list_servers():
        previous_status = str(server.get('last_health_status') or '')
        try:
            health = server_client(server).health()['data']
            merged = dict(server)
            merged.update(
                {
                    'public_host': health.get('public_host') or server.get('public_host') or '',
                    'host_mode': health.get('host_mode') or server.get('host_mode') or '',
                    'xray_port': int(health.get('xray_port') or server.get('xray_port') or 0),
                    'transport_mode': health.get('transport_mode') or server.get('transport_mode') or 'ws',
                    'ws_path': health.get('ws_path') or server.get('ws_path') or '/ws',
                    'reality_server_name': health.get('reality_server_name') or server.get('reality_server_name') or '',
                    'reality_public_key': health.get('reality_public_key') or server.get('reality_public_key') or '',
                    'reality_short_id': health.get('reality_short_id') or server.get('reality_short_id') or '',
                    'fingerprint': health.get('fingerprint') or server.get('fingerprint') or 'chrome',
                    'reality_port': int(health.get('reality_port') or server.get('reality_port') or 0),
                    'enabled': bool(server.get('enabled', 1)),
                    'last_health_status': 'ok',
                    'last_health_message': '',
                    'last_health_at': now_iso(),
                    'cpu_percent': health.get('cpu_percent', server.get('cpu_percent', 0)),
                    'memory_percent': health.get('memory_percent', server.get('memory_percent', 0)),
                    'disk_percent': health.get('disk_percent', server.get('disk_percent', 0)),
                    'load_1m': health.get('load_1m', server.get('load_1m', 0)),
                    'user_count': health.get('user_count', server.get('user_count', 0)),
                    'xray_active': bool(health.get('xray_active', server.get('xray_active', False))),
                    'updated_at': now_iso(),
                }
            )
            DB.add_or_update_server(merged)
            _notify_server_status_change(server, previous_status, 'ok', '')
            count += 1
        except Exception as exc:
            DB.update_server_health(server['name'], 'down', str(exc), now_iso())
            _notify_server_status_change(server, previous_status, 'down', str(exc))
            record_error(DB, LOGGER, component='scheduler', target_type='server', target_key=server['name'], message='refresh health failed', exc=exc)
    return count


def sync_usage_once() -> int:
    active_users = [u for u in DB.list_users() if u['is_active']]
    totals = {u['username']: 0 for u in active_users}
    per_server: dict[str, dict] = {}
    for user in active_users:
        for server in accessible_servers_for_user(user):
            bucket = per_server.setdefault(server['name'], {'server': server, 'users': set()})
            bucket['users'].add(user['username'])
    for item in per_server.values():
        server = item['server']
        try:
            stats_map = server_client(server).all_user_stats()['data'].get('stats', {})
            DB.update_server_health(server['name'], 'ok', '', now_iso(), {
                'cpu_percent': server.get('cpu_percent'),
                'memory_percent': server.get('memory_percent'),
                'disk_percent': server.get('disk_percent'),
                'load_1m': server.get('load_1m'),
                'user_count': len(item['users']),
                'xray_active': True,
            })
            DB.mark_server_sync(server['name'], now_iso())
        except Exception as exc:
            DB.update_server_health(server['name'], 'down', str(exc), now_iso())
            record_error(DB, LOGGER, component='scheduler', target_type='server', target_key=server['name'], message='sync usage failed', exc=exc)
            continue
        for username in item['users']:
            totals[username] = totals.get(username, 0) + int(stats_map.get(username, {}).get('total_bytes', 0))
    count = 0
    for username, total_bytes in totals.items():
        DB.sync_user_total_bytes(username, total_bytes, now_iso())
        count += 1
    return count


def disable_expired_once() -> int:
    count = 0
    for user in DB.list_expired_active_users(today_utc()):
        try:
            for server in accessible_servers_for_user(user):
                try:
                    server_client(server).disable_user(user['username'])
                except Exception as inner_exc:
                    record_error(DB, LOGGER, component='scheduler', target_type='server', target_key=server['name'], message=f'disable expired failed for {user["username"]}', exc=inner_exc)
            DB.set_active(user['username'], False, now_iso())
            DB.add_audit('disable_expired', 'user', user['username'], f"servers={','.join(DB.list_user_access_server_names(user['username'], enabled_only=False))}", now_iso(), 'system', 'system')
            count += 1
        except Exception as exc:
            record_error(DB, LOGGER, component='scheduler', target_type='user', target_key=user['username'], message='disable expired failed', exc=exc)
    return count


def disable_quota_once() -> int:
    count = 0
    for user in DB.list_over_quota_active_users():
        try:
            for server in accessible_servers_for_user(user):
                try:
                    server_client(server).disable_user(user['username'])
                except Exception as inner_exc:
                    record_error(DB, LOGGER, component='scheduler', target_type='server', target_key=server['name'], message=f'disable quota failed for {user["username"]}', exc=inner_exc)
            DB.set_active(user['username'], False, now_iso())
            DB.add_audit('disable_over_quota', 'user', user['username'], f"servers={','.join(DB.list_user_access_server_names(user['username'], enabled_only=False))}", now_iso(), 'system', 'system')
            count += 1
        except Exception as exc:
            record_error(DB, LOGGER, component='scheduler', target_type='user', target_key=user['username'], message='disable quota failed', exc=exc)
    return count


def warn_expiring_users() -> int:
    today = today_utc()
    count = 0
    for days_left in WARN_DAYS_SCHEDULE:
        cutoff = date_after_days(days_left)
        for user in DB.list_expiring_soon(today, cutoff):
            if DB.warning_sent(user['username'], 'expiry', str(days_left)):
                continue
            text = (
                f"⚠️ نزدیک به انقضا\n"
                f"کاربر: {user['username']}\n"
                f"سرورها: {_server_summary_for_user(user['username'])}\n"
                f"انقضا: {user['expire_date']}\n"
                f"باقی‌مانده: {days_left} روز یا کمتر"
            )
            try:
                NOTIFIER.message(text)
                DB.mark_warning_sent(user['username'], 'expiry', str(days_left), now_iso())
                count += 1
            except Exception as exc:
                LOGGER.warning('warn_expiring_failed user=%s level=%s error=%s', user['username'], days_left, exc)
    return count


def warn_quota_users() -> int:
    count = 0
    for threshold in WARN_USAGE_SCHEDULE:
        for user in DB.list_quota_reached_threshold(threshold):
            if DB.warning_sent(user['username'], 'quota', str(threshold)):
                continue
            text = (
                f"⚠️ نزدیک به اتمام حجم\n"
                f"کاربر: {user['username']}\n"
                f"سرورها: {_server_summary_for_user(user['username'])}\n"
                f"مصرف: {user['used_gb']}/{user['traffic_gb']} GB\n"
                f"آستانه: {threshold}%"
            )
            try:
                NOTIFIER.message(text)
                DB.mark_warning_sent(user['username'], 'quota', str(threshold), now_iso())
                count += 1
            except Exception as exc:
                LOGGER.warning('warn_quota_failed user=%s threshold=%s error=%s', user['username'], threshold, exc)
    return count


def send_daily_report_if_needed() -> bool:
    today = today_utc()
    if DB.get_meta('last_daily_report_date') == today:
        return False
    users = DB.list_users()
    servers = DB.list_servers()
    lines = [
        '📊 گزارش روزانه Sahar',
        f'Date: {today}',
        f'Servers: {len(servers)}',
        f'Users: {len(users)}',
        f'Active users: {sum(1 for u in users if u["is_active"])}',
        f'Expired active users: {len(DB.list_expired_active_users(today))}',
        f'Over quota active users: {len(DB.list_over_quota_active_users())}',
    ]
    for server in servers[:15]:
        lines.append(
            f"- {server['name']} | {server.get('last_health_status') or 'unknown'} | cpu {server.get('cpu_percent',0)}% | ram {server.get('memory_percent',0)}% | disk {server.get('disk_percent',0)}%"
        )
    NOTIFIER.message('\n'.join(lines))
    DB.set_meta('last_daily_report_date', today)
    return True


def send_weekly_report_if_needed() -> bool:
    week_key = datetime.utcnow().strftime('%G-W%V')
    if DB.get_meta('last_weekly_report_key') == week_key:
        return False
    users = DB.list_users()
    servers = DB.list_servers()
    lines = [
        '🗓 گزارش هفتگی Sahar',
        f'Week: {week_key}',
        f'کل سرورها: {len(servers)}',
        f'کل کاربران: {len(users)}',
        f'فعال: {sum(1 for u in users if u["is_active"])}',
        f'غیرفعال: {sum(1 for u in users if not u["is_active"])}',
    ]
    top = sorted(users, key=lambda u: float(u.get('used_gb') or 0), reverse=True)[:5]
    if top:
        lines.append('Top 5 مصرف:')
        for user in top:
            lines.append(f"- {user['username']} | {user['used_gb']} GB | {_server_summary_for_user(user['username'])}")
    NOTIFIER.message('\n'.join(lines))
    DB.set_meta('last_weekly_report_key', week_key)
    return True


def periodic_backup_if_needed() -> bool:
    last = DB.get_meta('last_backup_at')
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if datetime.utcnow() - last_dt < timedelta(hours=BACKUP_INTERVAL_HOURS):
                return False
        except ValueError:
            pass
    result = BACKUPS.create_backup(DB.list_servers())
    DB.set_meta('last_backup_at', now_iso())
    NOTIFIER.document(result['path'], caption='Scheduled backup')
    return True


def main() -> None:
    LOGGER.info('scheduler_started interval=%s', INTERVAL_SECONDS)
    while True:
        try:
            healthy = refresh_health_cache()
            synced = sync_usage_once()
            disabled_expired = disable_expired_once()
            disabled_quota = disable_quota_once()
            warned_expiry = warn_expiring_users()
            warned_quota = warn_quota_users()
            sent_report = send_daily_report_if_needed()
            sent_weekly = send_weekly_report_if_needed()
            created_backup = periodic_backup_if_needed()
            cf_synced_count, _cf_names = sync_cloudflare_if_needed()
            LOGGER.info(
                'scheduler_cycle healthy=%s synced=%s expired=%s quota=%s warn_expiry=%s warn_quota=%s report=%s weekly=%s backup=%s cloudflare_synced=%s',
                healthy, synced, disabled_expired, disabled_quota, warned_expiry, warned_quota, sent_report, sent_weekly, created_backup, cf_synced_count,
            )
        except Exception:
            LOGGER.exception('scheduler_cycle_failed')
        time.sleep(INTERVAL_SECONDS)


if __name__ == '__main__':
    main()
