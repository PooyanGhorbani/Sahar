from __future__ import annotations

from typing import Any, Dict, List


def _state_badge(state: str) -> str:
    state = (state or '').strip().lower()
    mapping = {
        'active': '🟢 فعال',
        'ok': '🟢 سالم',
        'inactive': '🔴 غیرفعال',
        'disabled': '⚪ غیرفعال',
        'failed': '🔴 خطا',
        'unknown': '🟠 نامشخص',
    }
    return mapping.get(state, f"🟠 {state or 'نامشخص'}")


def build_dashboard_text(
    *,
    users: List[Dict[str, Any]],
    servers: List[Dict[str, Any]],
    version: str,
    bot_state: str,
    scheduler_state: str,
    subscription_state: str,
    local_agent_state: str,
    expired_count: int,
    quota_count: int,
    error_count: int,
) -> str:
    active_users = sum(1 for u in users if u.get('is_active'))
    enabled_servers = [s for s in servers if s.get('enabled')]
    healthy_servers = sum(1 for s in enabled_servers if (s.get('last_health_status') or '') == 'ok')
    unhealthy_servers = max(len(enabled_servers) - healthy_servers, 0)

    attention = []
    if unhealthy_servers:
        attention.append(f'سرور مشکل‌دار: {unhealthy_servers}')
    if expired_count:
        attention.append(f'کاربر منقضی فعال: {expired_count}')
    if quota_count:
        attention.append(f'هشدار مصرف: {quota_count}')
    if error_count:
        attention.append(f'خطای اخیر: {error_count}')
    attention_line = ' | '.join(attention) if attention else 'همه‌چیز پایدار است.'

    return '\n'.join(
        [
            '<b>Sahar Control Panel</b>',
            '',
            f'👥 کاربران: {len(users)} | فعال: {active_users}',
            f'🌐 سرورها: {len(servers)} | سالم: {healthy_servers} | مشکل‌دار: {unhealthy_servers}',
            f'⌛ کاربران منقضی فعال: {expired_count}',
            f'📉 هشدار مصرف: {quota_count}',
            f'🧯 خطاهای اخیر: {error_count}',
            f'🤖 بات: {_state_badge(bot_state)}',
            f'⏱ زمان‌بند: {_state_badge(scheduler_state)}',
            f'🔗 سابسکریپشن: {_state_badge(subscription_state)}',
            f'🛰 ایجنت محلی: {_state_badge(local_agent_state)}',
            f'📌 جمع‌بندی: {attention_line}',
            f'📦 نسخه: {version or "-"}',
        ]
    )


def merge_server_runtime_update(server: Dict[str, Any], health: Dict[str, Any], checked_at: str) -> Dict[str, Any]:
    return {
        'name': server['name'],
        'api_url': server['api_url'],
        'api_token': server['api_token'],
        'api_tls_fingerprint': health.get('tls_fingerprint') or server.get('api_tls_fingerprint', ''),
        'public_host': health.get('public_host') or server.get('public_host') or '',
        'host_mode': health.get('host_mode') or server.get('host_mode') or '',
        'xray_port': int(health.get('simple_port') or health.get('xray_port') or server.get('xray_port') or 0),
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
        'last_health_at': checked_at,
        'cpu_percent': health.get('cpu_percent', server.get('cpu_percent', 0)),
        'memory_percent': health.get('memory_percent', server.get('memory_percent', 0)),
        'disk_percent': health.get('disk_percent', server.get('disk_percent', 0)),
        'load_1m': health.get('load_1m', server.get('load_1m', 0)),
        'user_count': health.get('user_count', server.get('user_count', 0)),
        'xray_active': bool(health.get('xray_active', server.get('xray_active', False))),
        'last_sync_at': server.get('last_sync_at', ''),
        'cf_zone_id': server.get('cf_zone_id', ''),
        'cf_record_id': server.get('cf_record_id', ''),
        'cf_record_type': server.get('cf_record_type', ''),
        'cf_dns_name': server.get('cf_dns_name', ''),
        'cf_tunnel_id': server.get('cf_tunnel_id', ''),
        'cf_tunnel_name': server.get('cf_tunnel_name', ''),
        'cf_tunnel_status': server.get('cf_tunnel_status', ''),
        'provisioning_state': server.get('provisioning_state', 'healthy'),
        'provisioning_message': server.get('provisioning_message', ''),
        'created_at': server['created_at'],
        'updated_at': checked_at,
    }
