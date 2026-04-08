from __future__ import annotations

import asyncio
import contextvars
import logging
import math
import os
import secrets
import socket
import tempfile
import time
import uuid
from functools import wraps
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent_client import AgentClient
from backup_manager import BackupManager
from provisioner import ProvisionError, SSHProvisioner
from cloudflare_manager import CloudflareError, CloudflareManager
from db import Database
from error_tools import record_error
from utils import (
    add_days,
    build_vless_link,
    calc_expire,
    export_users_csv,
    load_config,
    now_iso,
    setup_logging,
    systemctl_is_active,
    today_utc,
    valid_server_name,
    valid_username,
    write_qr_file,
)

CONFIG_PATH = os.environ.get('SAHAR_CONFIG', '/opt/sahar-master/data/config.json')
config = load_config(CONFIG_PATH)
setup_logging(config['log_path'])
LOGGER = logging.getLogger(__name__)
DB = Database(config['database_path'])
BACKUPS = BackupManager(config, DB)
CLOUDFLARE = CloudflareManager(config, DB)
ADMIN_IDS = set(config.get('admin_ids') or [])
AGENT_TIMEOUT = int(config.get('agent_timeout_seconds', 15))
PAGE_SIZE = 8
AWAITING_KEY = 'awaiting_input'
WIZARD_KEY = 'create_user_wizard'
CONFIRM_KEY = 'pending_confirm'
SSH_WIZARD_KEY = 'ssh_server_wizard'
CONFIRM_TTL_SECONDS = 180
ROLE_LEVELS = {'viewer': 1, 'support': 2, 'admin': 3, 'owner': 4}
ROLE_LABELS = {'owner': 'مالک', 'admin': 'ادمین', 'support': 'پشتیبان', 'viewer': 'مشاهده‌گر'}
AUDIT_ACTOR = contextvars.ContextVar('audit_actor', default={'chat_id': 'system', 'role': 'system'})
PLAN_PRESETS = [('trial', '🧪 تست'), ('bronze', '🥉 برنزی'), ('silver', '🥈 نقره‌ای'), ('gold', '🥇 طلایی'), ('vip', '👑 ویژه')]
NOTE_PRESETS = [('manual', '🛠 دستی'), ('gift', '🎁 هدیه'), ('telegram', '📨 تلگرام'), ('support', '🎧 پشتیبانی'), ('urgent', '🚨 فوری')]
TRAFFIC_PRESETS = [10, 20, 50, 100, 200, 500]
DAY_PRESETS = [7, 30, 60, 90, 180, 365]


def bootstrap_admins() -> None:
    existing = DB.list_admins()
    if existing:
        return
    now = now_iso()
    ids = list(config.get('admin_ids') or [])
    if not ids:
        return
    DB.upsert_admin(ids[0], 'owner', 'Owner', now, now, True)
    for chat_id in ids[1:]:
        DB.upsert_admin(chat_id, 'admin', 'Admin', now, now, True)


def admin_record(chat_id: str) -> Optional[Dict[str, Any]]:
    return DB.get_admin(str(chat_id))


def role_of_chat(chat_id: str) -> str:
    row = admin_record(str(chat_id))
    if row and row.get('enabled'):
        return row.get('role') or 'viewer'
    return ''


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role or 'نامشخص')


def has_role(chat_id: str, minimum_role: str = 'support') -> bool:
    role = role_of_chat(str(chat_id))
    if not role:
        return False
    return ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS.get(minimum_role, 1)


def is_admin(update: Update) -> bool:
    return bool(update.effective_chat) and has_role(str(update.effective_chat.id), 'viewer')


async def deny_if_not_admin(update: Update, minimum_role: str = 'support') -> bool:
    if update.effective_chat and has_role(str(update.effective_chat.id), minimum_role):
        return False
    target = update.effective_message
    if target:
        await target.reply_text(f'⛔ دسترسی ندارید. حداقل سطح لازم: {role_label(minimum_role)}')
    return True


def role_required(minimum_role: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            if await deny_if_not_admin(update, minimum_role):
                return
            actor = {'chat_id': str(update.effective_chat.id) if update.effective_chat else 'system', 'role': role_of_chat(str(update.effective_chat.id)) if update.effective_chat else 'system'}
            token = AUDIT_ACTOR.set(actor)
            try:
                return await func(update, context, *args, **kwargs)
            finally:
                AUDIT_ACTOR.reset(token)
        return wrapper
    return decorator


def admin_only(func: Callable) -> Callable:
    return role_required('viewer')(func)


async def respond(update: Update, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    if update.callback_query:
        query = update.callback_query
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            await query.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    elif update.effective_message:
        await update.effective_message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def send_temp(update: Update, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def safe_answer(query) -> None:
    try:
        await query.answer()
    except Exception:
        pass


def audit(action: str, target_type: str, target_key: str, details: str = '') -> None:
    actor = AUDIT_ACTOR.get() or {'chat_id': 'system', 'role': 'system'}
    DB.add_audit(action, target_type, target_key, details, now_iso(), str(actor.get('chat_id', 'system')), str(actor.get('role', 'system')))





def role_rank(role: str) -> int:
    return ROLE_LEVELS.get(role or '', 0)


def current_prompt(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return dict(context.user_data.get(AWAITING_KEY) or {})


def set_prompt(context: ContextTypes.DEFAULT_TYPE, action: str, subject: str = '') -> None:
    context.user_data[AWAITING_KEY] = {'action': action, 'subject': subject}


def clear_prompt(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(AWAITING_KEY, None)


def current_wizard(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return dict(context.user_data.get(WIZARD_KEY) or {})


def set_wizard(context: ContextTypes.DEFAULT_TYPE, payload: dict) -> None:
    context.user_data[WIZARD_KEY] = payload


def clear_wizard(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(WIZARD_KEY, None)


def current_ssh_wizard(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return dict(context.user_data.get(SSH_WIZARD_KEY) or {})


def set_ssh_wizard(context: ContextTypes.DEFAULT_TYPE, payload: dict) -> None:
    context.user_data[SSH_WIZARD_KEY] = payload


def clear_ssh_wizard(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(SSH_WIZARD_KEY, None)


def current_confirmation(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return dict(context.user_data.get(CONFIRM_KEY) or {})


def set_confirmation(context: ContextTypes.DEFAULT_TYPE, action: str, subject: str) -> str:
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    context.user_data[CONFIRM_KEY] = {
        'action': action,
        'subject': subject,
        'code': code,
        'expires_at': time.time() + CONFIRM_TTL_SECONDS,
    }
    return code


def clear_confirmation(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(CONFIRM_KEY, None)


def resolve_plan_label(plan_key: str) -> str:
    if not plan_key:
        return '-'
    plan = DB.get_plan(plan_key)
    if plan:
        return plan.get('label') or plan_key
    for key, label in PLAN_PRESETS:
        if key == plan_key:
            return label
    return plan_key


def generate_username() -> str:
    return f"u{secrets.randbelow(10**8):08d}"


def format_user_brief(user: Dict[str, Any]) -> str:
    status = '🟢' if user.get('is_active') else '⚫️'
    return f"{status} <b>{user['username']}</b> | {user.get('server_name','-')} | {user.get('used_gb',0)}/{user.get('traffic_gb',0)} GB | {user.get('expire_date','-')}"


def status_text() -> str:
    users = DB.list_users()
    servers = DB.list_servers()
    active_users = sum(1 for u in users if u.get('is_active'))
    healthy_servers = sum(1 for s in servers if s.get('enabled') and (s.get('last_health_status') or '') == 'ok')
    bot_state = 'active' if systemctl_is_active('sahar-master-bot') else 'inactive'
    scheduler_state = 'active' if systemctl_is_active('sahar-master-scheduler') else 'inactive'
    subscription_state = 'active' if systemctl_is_active('sahar-master-subscription') else 'inactive'
    if config.get('local_node_enabled'):
        local_agent_state = 'active' if systemctl_is_active('sahar-master-local-agent') else 'inactive'
    else:
        local_agent_state = 'disabled'
    return "\n".join([
        '<b>Sahar Control Panel</b>',
        '',
        f'👥 Users: {len(users)} | Active: {active_users}',
        f'🌐 Servers: {len(servers)} | Healthy: {healthy_servers}',
        f'🤖 Bot: {bot_state}',
        f'⏱ Scheduler: {scheduler_state}',
        f'🔗 Subscription: {subscription_state}',
        f'🛰 Local Agent: {local_agent_state}',
        f'📦 Version: {config.get("package_version") or "-"}',
    ])


def server_client(server: Dict[str, Any]) -> AgentClient:
    return AgentClient(server['api_url'], server['api_token'], timeout=AGENT_TIMEOUT)


def refresh_server_metadata(server_name: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    server = DB.get_server(server_name)
    if not server:
        raise ValueError('server not found')
    client = server_client(server)
    health = client.health().get('data', {})
    DB.add_or_update_server({
        'name': server['name'],
        'api_url': server['api_url'],
        'api_token': server['api_token'],
        'public_host': health.get('public_host') or server.get('public_host') or '',
        'host_mode': health.get('host_mode') or server.get('host_mode') or '',
        'xray_port': int(health.get('simple_port') or health.get('xray_port') or server.get('xray_port') or 0),
        'transport_mode': health.get('transport_mode') or server.get('transport_mode') or 'tcp',
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
        'last_sync_at': server.get('last_sync_at', ''),
        'cf_zone_id': server.get('cf_zone_id', ''),
        'cf_record_id': server.get('cf_record_id', ''),
        'cf_dns_name': server.get('cf_dns_name', ''),
        'provisioning_state': server.get('provisioning_state', 'healthy'),
        'provisioning_message': server.get('provisioning_message', ''),
        'created_at': server['created_at'],
        'updated_at': now_iso(),
    })
    return DB.get_server(server_name), health


def _server_score(server: Dict[str, Any]) -> float:
    if not server.get('enabled'):
        return 10**9
    score = 0.0
    score += float(server.get('cpu_percent') or 0) * 1.5
    score += float(server.get('memory_percent') or 0) * 1.2
    score += float(server.get('disk_percent') or 0) * 0.8
    score += float(server.get('load_1m') or 0) * 10
    score += float(server.get('user_count') or 0)
    if (server.get('last_health_status') or '') != 'ok':
        score += 1000
    return score


def preferred_server_for_quick_create() -> Dict[str, Any]:
    servers = DB.list_servers(enabled_only=True)
    if not servers:
        raise ValueError('no enabled server found')
    return sorted(servers, key=_server_score)[0]


def _provision_user_on_access_servers(username: str, uuid_value: str, server_names: List[str]) -> None:
    for name in server_names:
        server = DB.get_server(name)
        if not server or not server.get('enabled'):
            continue
        try:
            server_client(server).add_user(username, uuid_value)
        except Exception:
            LOGGER.exception('provision_user_on_server_failed user=%s server=%s', username, name)


def create_user_on_server(server: Dict[str, Any], username: str, traffic_gb: int, days: int, notes: str = '', plan: str = '') -> Dict[str, Any]:
    if not server:
        raise ValueError('server not found')
    if DB.get_user(username):
        raise ValueError('username already exists')
    uuid_value = str(uuid.uuid4())
    expire = calc_expire(days)
    now = now_iso()
    DB.add_user(username, int(server['id']), uuid_value, int(traffic_gb), expire, notes or '', plan or '', now, now)
    DB.ensure_subscription_token(username, secrets.token_urlsafe(24), now)
    set_user_access_all(DB.get_user(username), provision=False)
    access_servers = DB.list_user_access_servers(username, enabled_only=True)
    _provision_user_on_access_servers(username, uuid_value, [s['name'] for s in access_servers])
    audit('create_user', 'user', username, f"server={server['name']};traffic={traffic_gb};days={days}")
    return DB.get_user(username)


def disable_user_on_server(user: Dict[str, Any]) -> None:
    for server in DB.list_user_access_servers(user['username'], enabled_only=True):
        try:
            server_client(server).disable_user(user['username'])
        except Exception:
            LOGGER.exception('disable_user_failed user=%s server=%s', user['username'], server['name'])
    DB.set_active(user['username'], False, now_iso())


def enable_user_on_server(user: Dict[str, Any]) -> None:
    for server in DB.list_user_access_servers(user['username'], enabled_only=True):
        try:
            server_client(server).enable_user(user['username'], user['uuid'])
        except Exception:
            LOGGER.exception('enable_user_failed user=%s server=%s', user['username'], server['name'])
    DB.set_active(user['username'], True, now_iso())


def delete_user_everywhere(user: Dict[str, Any]) -> None:
    for server in DB.list_user_access_servers(user['username'], enabled_only=False):
        try:
            server_client(server).remove_user(user['username'])
        except Exception:
            LOGGER.exception('delete_user_failed user=%s server=%s', user['username'], server['name'])
    DB.delete_user(user['username'])


def prepare_server_delete(server: Dict[str, Any]) -> None:
    primary_users = DB.list_primary_users_for_server(int(server['id']))
    for user in primary_users:
        alternatives = [s for s in DB.list_user_access_servers(user['username'], enabled_only=False) if int(s['id']) != int(server['id'])]
        if not alternatives:
            raise ValueError(f"کاربر {user['username']} هیچ سرور جایگزینی ندارد")
        DB.set_server_for_user(user['username'], int(alternatives[0]['id']), now_iso())
    delete_server_dns(server)
    DB.delete_server(server['name'])


def sync_usage_once() -> int:
    from scheduler import sync_usage_once as _sync_usage_once
    return _sync_usage_once()


def cleanup_expired_once() -> int:
    from scheduler import disable_expired_once
    return disable_expired_once()


def cleanup_quota_once() -> int:
    from scheduler import disable_quota_once
    return disable_quota_once()


def _detect_public_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('8.8.8.8', 80))
            return sock.getsockname()[0]
    except OSError:
        return ''



def subscription_url_for_user(username: str) -> str:
    token = DB.get_subscription_token(username)
    if not token:
        token = DB.ensure_subscription_token(username, secrets.token_urlsafe(24), now_iso())
    base = (config.get('subscription_base_url') or '').rstrip('/')
    if not base:
        bind_host = str(config.get('subscription_bind_host') or '127.0.0.1').strip()
        bind_port = config.get('subscription_bind_port') or 8080
        host = bind_host
        if bind_host in {'0.0.0.0', '::', '', '127.0.0.1', 'localhost'}:
            host = _detect_public_ipv4() or bind_host
        base = f'http://{host}:{bind_port}'
    return f'{base}/sub/{token}'


def set_user_access_all(user: Dict[str, Any], provision: bool = True) -> None:
    username = user['username']
    DB.set_user_access_mode(username, 'all', now_iso())
    DB.clear_user_server_access(username)
    if provision:
        _provision_user_on_access_servers(username, user['uuid'], [s['name'] for s in DB.list_servers(enabled_only=True)])


def set_user_access_selected(user: Dict[str, Any], server_names: List[str]) -> None:
    username = user['username']
    DB.set_user_access_mode(username, 'selected', now_iso())
    DB.clear_user_server_access(username)
    selected = []
    for name in server_names:
        if DB.get_server(name):
            DB.grant_user_server_access(username, name, now_iso())
            selected.append(name)
    for server in DB.list_servers(enabled_only=True):
        if server['name'] not in selected:
            try:
                server_client(server).remove_user(username)
            except Exception:
                LOGGER.exception('remove_user_nonselected_failed user=%s server=%s', username, server['name'])
    _provision_user_on_access_servers(username, user['uuid'], selected)


def delete_server_dns(server: Dict[str, Any]) -> None:
    if not getattr(CLOUDFLARE, 'enabled', False):
        LOGGER.info('delete_server_dns_skipped server=%s reason=cloudflare_disabled', server.get('name'))
        return
    try:
        CLOUDFLARE.delete_server_dns(server)
    except Exception:
        LOGGER.exception('delete_server_dns_failed server=%s', server.get('name'))


def _resolve_target_ip_for_dns(host: str) -> str:
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        try:
            return socket.gethostbyname(host)
        except OSError as exc:
            raise CloudflareError(f'failed to resolve SSH host to IPv4: {host}') from exc


def do_add_server_via_ssh(name: str, host: str, ssh_port: int, ssh_username: str, ssh_password: str) -> str:
    project_root = Path(CONFIG_PATH).resolve().parent.parent
    mark_server_stage(name, 'provisioning', 'connecting over ssh')
    provisioner = SSHProvisioner(project_root=project_root, timeout=AGENT_TIMEOUT)
    api_url, api_token, _health = provisioner.provision_agent(
        server_name=name,
        host=host,
        ssh_port=ssh_port,
        ssh_username=ssh_username,
        ssh_password=ssh_password,
    )
    result = do_add_server(name, api_url, api_token)
    server = DB.get_server(name)
    if server:
        try:
            target_ip = _resolve_target_ip_for_dns(host)
            dns_info = CLOUDFLARE.ensure_server_dns(name, target_ip)
            updated = DB.get_server(name) or server
            updated['cf_zone_id'] = dns_info.get('zone_id', '')
            updated['cf_record_id'] = dns_info.get('record_id', '')
            updated['cf_dns_name'] = dns_info.get('dns_name', '')
            updated['public_host'] = dns_info.get('dns_name') or updated.get('public_host') or host
            DB.add_or_update_server(updated)
        except Exception:
            LOGGER.exception('cloudflare_ensure_failed server=%s', name)
    return result


def _menu_button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_menu_button('👤 کاربران', 'menu:users:0'), _menu_button('🌐 سرورها', 'menu:servers:0')],
        [_menu_button('📊 گزارش‌ها', 'menu:reports'), _menu_button('🧰 ابزارها', 'menu:tools')],
        [_menu_button('➕ ساخت کاربر', 'wizard:create_user'), _menu_button('🚀 افزودن سرور با SSH', 'wizard:add_server_ssh')],
        [_menu_button('❓ راهنما', 'menu:help')],
    ])


def users_page_markup(users: List[Dict[str, Any]], page: int) -> InlineKeyboardMarkup:
    rows = [[_menu_button(f"👤 {u['username']}", f"user:{u['username']}")] for u in users[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    nav = []
    if page > 0:
        nav.append(_menu_button('◀️', f'menu:users:{page - 1}'))
    if (page + 1) * PAGE_SIZE < len(users):
        nav.append(_menu_button('▶️', f'menu:users:{page + 1}'))
    if nav:
        rows.append(nav)
    rows.append([_menu_button('🏠 خانه', 'menu:home')])
    return InlineKeyboardMarkup(rows)


def servers_page_markup(servers: List[Dict[str, Any]], page: int) -> InlineKeyboardMarkup:
    rows = [[_menu_button(f"🌐 {s['name']}", f"server:{s['id']}")] for s in servers[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    nav = []
    if page > 0:
        nav.append(_menu_button('◀️', f'menu:servers:{page - 1}'))
    if (page + 1) * PAGE_SIZE < len(servers):
        nav.append(_menu_button('▶️', f'menu:servers:{page + 1}'))
    if nav:
        rows.append(nav)
    rows.append([_menu_button('🏠 خانه', 'menu:home')])
    return InlineKeyboardMarkup(rows)


def user_detail_markup(user: Dict[str, Any]) -> InlineKeyboardMarkup:
    username = user['username']
    return InlineKeyboardMarkup([
        [_menu_button('🔗 لینک', f'act:link:{username}'), _menu_button('📷 QR', f'act:qr:{username}')],
        [_menu_button('♻️ ریست مصرف', f'act:reset_usage:{username}'), _menu_button('⛔ غیرفعال', f'act:confirm:disable:{username}')],
        [_menu_button('✅ فعال', f'act:enable:{username}'), _menu_button('🗑 حذف', f'act:confirm:delete:{username}')],
        [_menu_button('🏠 خانه', 'menu:home')],
    ])


def server_detail_markup(server: Dict[str, Any]) -> InlineKeyboardMarkup:
    sid = int(server['id'])
    rows = [
        [_menu_button('💚 Health', f'act:server_health:{sid}'), _menu_button('👥 کاربران', f'act:server_users:{sid}')],
        [_menu_button('✅ فعال', f'act:enable_server:{sid}'), _menu_button('⛔ غیرفعال', f'act:confirm:disable_server:{sid}')],
        [_menu_button('🗑 حذف', f'act:confirm:remove_server:{sid}')],
        [_menu_button('🏠 خانه', 'menu:home')],
    ]
    return InlineKeyboardMarkup(rows)


def reports_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_menu_button('⌛ منقضی‌ها', 'report:expired'), _menu_button('📉 تمام‌حجم‌ها', 'report:quota')],
        [_menu_button('🔄 sync مصرف', 'report:sync_usage'), _menu_button('🧹 cleanup', 'report:cleanup')],
        [_menu_button('🧾 audit', 'report:audits'), _menu_button('🏠 خانه', 'menu:home')],
    ])


def tools_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_menu_button('💾 بکاپ', 'tool:backup_now'), _menu_button('📤 ارسال بکاپ', 'tool:send_backup')],
        [_menu_button('📄 CSV کاربران', 'tool:export_users'), _menu_button('📊 وضعیت', 'tool:status')],
        [_menu_button('🛡 ادمین‌ها', 'tool:list_admins'), _menu_button('📦 پلن‌ها', 'tool:list_plans')],
        [_menu_button('🏠 خانه', 'menu:home')],
    ])


def wizard_username_markup(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_menu_button('🎲 نام جدید', 'wizard_username:regen'), _menu_button('➡️ ادامه', 'wizard_username:next')],
        [_menu_button(f'پیشنهادی: {username}', 'act:noop')],
        [_menu_button('❌ لغو', 'wizard:cancel')],
    ])


def wizard_value_markup(kind: str, current: int) -> InlineKeyboardMarkup:
    presets = TRAFFIC_PRESETS if kind == 'traffic' else DAY_PRESETS
    label = 'wizard_traffic' if kind == 'traffic' else 'wizard_days'
    row1 = [_menu_button(str(v), f'{label}:set:{v}') for v in presets[:3]]
    row2 = [_menu_button(str(v), f'{label}:set:{v}') for v in presets[3:6]]
    row3 = [_menu_button('-1', f'{label}:delta:-1'), _menu_button('+1', f'{label}:delta:1'), _menu_button('➡️ ادامه', f'{label}:next:0')]
    return InlineKeyboardMarkup([row1, row2, row3, [_menu_button(f'مقدار فعلی: {current}', 'act:noop')], [_menu_button('❌ لغو', 'wizard:cancel')]])


def wizard_plan_markup() -> InlineKeyboardMarkup:
    plans = DB.list_plans(enabled_only=True)
    rows = [[_menu_button(plan['label'], f"wizard_plan:set:{plan['key']}")] for plan in plans[:12]]
    rows.append([_menu_button('⏭ رد کردن', 'wizard_plan:skip')])
    rows.append([_menu_button('❌ لغو', 'wizard:cancel')])
    return InlineKeyboardMarkup(rows)


def wizard_note_markup() -> InlineKeyboardMarkup:
    rows = [[_menu_button(label, f'note_preset:{key}')] for key, label in NOTE_PRESETS]
    rows.append([_menu_button('⏭ رد کردن', 'wizard_note:skip')])
    rows.append([_menu_button('❌ لغو', 'wizard:cancel')])
    return InlineKeyboardMarkup(rows)


def wizard_skip_markup(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_menu_button('⏭ رد کردن', f'wizard_{kind}:skip')], [_menu_button('❌ لغو', 'wizard:cancel')]])


def wizard_summary_text(data: Dict[str, Any]) -> str:
    server_label = data.get('server_name') if data.get('server_mode') == 'manual' else 'بهترین سرور'
    return "\n".join([
        '<b>تأیید ساخت کاربر</b>',
        '',
        f"👤 نام: {data.get('username', '-')}",
        f"🌐 سرور: {server_label}",
        f"📦 حجم: {data.get('traffic_gb', '-')} GB",
        f"📅 زمان: {data.get('days', '-')} روز",
        f"🏷 پلن: {resolve_plan_label(data.get('plan', ''))}",
        f"📝 یادداشت: {data.get('notes') or '-'}",
    ])


def wizard_confirm_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_menu_button('✅ ساخت کاربر', 'wizard_confirm:create')], [_menu_button('❌ لغو', 'wizard:cancel')]])


async def start_create_user_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_prompt(context)
    clear_wizard(context)
    servers = DB.list_servers(enabled_only=True)
    rows = [[_menu_button('⚡ انتخاب خودکار بهترین سرور', 'wizard_server:auto')]]
    rows.extend([[_menu_button(f"🌐 {s['name']}", f"wizard_server:id:{s['id']}")] for s in servers[:20]])
    rows.append([_menu_button('❌ لغو', 'wizard:cancel')])
    await respond(update, 'مرحله ۱ از ۶\nسرور را انتخاب کن.', InlineKeyboardMarkup(rows))


def show_admins_text() -> str:
    rows = DB.list_admins()
    lines = [f"• <code>{a['chat_id']}</code> | {role_label(a['role'])} | {'فعال' if a['enabled'] else 'غیرفعال'}" for a in rows]
    return list_text('مدیریت ادمین‌ها', lines)


async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admins = DB.list_admins()
    rows = [[_menu_button(f"🛡 {a['chat_id']} | {role_label(a['role'])}", f"admin:{a['chat_id']}")] for a in admins]
    rows.append([_menu_button('➕ مالک', 'admin_add:owner'), _menu_button('➕ ادمین', 'admin_add:admin')])
    rows.append([_menu_button('➕ پشتیبان', 'admin_add:support'), _menu_button('➕ مشاهده‌گر', 'admin_add:viewer')])
    rows.append([_menu_button('🏠 خانه', 'menu:home')])
    await respond(update, show_admins_text(), InlineKeyboardMarkup(rows))


async def show_admin_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: str) -> None:
    target = DB.get_admin(chat_id)
    if not target:
        await send_temp(update, '❌ ادمین پیدا نشد')
        return
    text = "\n".join([
        '<b>ادمین</b>',
        '',
        f'<code>{chat_id}</code>',
        f"نقش: {role_label(target['role'])}",
        f"وضعیت: {'فعال' if target['enabled'] else 'غیرفعال'}",
    ])
    rows = [
        [_menu_button('مالک', f'admin_role:{chat_id}:owner'), _menu_button('ادمین', f'admin_role:{chat_id}:admin')],
        [_menu_button('پشتیبان', f'admin_role:{chat_id}:support'), _menu_button('مشاهده‌گر', f'admin_role:{chat_id}:viewer')],
        [_menu_button('✅ فعال', f'admin_enable:{chat_id}'), _menu_button('⛔ غیرفعال', f'admin_disable:{chat_id}')],
        [_menu_button('🗑 حذف', f'admin_remove:{chat_id}')],
        [_menu_button('↩️ برگشت', 'tool:list_admins')],
    ]
    await respond(update, text, InlineKeyboardMarkup(rows))


def setting_display_value(key: str) -> str:
    if key == 'cloudflare_api_token':
        return 'configured' if CLOUDFLARE.get_token() else 'not set'
    value = config.get(key)
    if isinstance(value, bool):
        return 'on' if value else 'off'
    if value in (None, ''):
        return '-'
    return str(value)


def settings_menu_markup() -> InlineKeyboardMarkup:
    order = [
        'subscription_base_url',
        'scheduler_interval_seconds',
        'agent_timeout_seconds',
        'warn_days_left',
        'warn_usage_percent',
        'backup_interval_hours',
        'backup_retention',
        'cloudflare_enabled',
        'cloudflare_domain_name',
        'cloudflare_base_subdomain',
        'cloudflare_api_token',
    ]
    rows = [[_menu_button(f"⚙️ {EDITABLE_SETTINGS[key]['label']}", f'setting:edit:{key}')] for key in order]
    rows.append([_menu_button('🏠 خانه', 'menu:home')])
    return InlineKeyboardMarkup(rows)


def settings_text() -> str:
    lines = [f"• {meta['label']}: <code>{setting_display_value(key)}</code>" for key, meta in EDITABLE_SETTINGS.items()]
    lines.append('بعد از ذخیره، اگر لازم باشد سرویس‌های مربوطه خودکار ری‌استارت می‌شوند.')
    return list_text('تنظیمات مستر', lines)


async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, settings_text(), settings_menu_markup())


def refresh_runtime_config() -> None:
    global AGENT_TIMEOUT, ADMIN_IDS
    config['admin_ids'] = parse_admin_ids(config.get('admin_chat_ids', ''))
    ADMIN_IDS = set(config.get('admin_ids') or [])
    AGENT_TIMEOUT = int(config.get('agent_timeout_seconds', 15))
    CLOUDFLARE.config = config
    CLOUDFLARE.enabled = bool(config.get('cloudflare_enabled')) and bool(config.get('cloudflare_domain_name') or config.get('cloudflare_zone_name'))


def persist_master_config() -> None:
    save_config(CONFIG_PATH, config)


def parse_setting_value(key: str, raw: str) -> tuple[Any, str]:
    meta = EDITABLE_SETTINGS[key]
    value = raw.strip()
    if meta['type'] == 'int':
        number = int(value)
        if 'min' in meta and number < int(meta['min']):
            raise ValueError(f"حداقل مقدار برای {meta['label']} برابر {meta['min']} است")
        if 'max' in meta and number > int(meta['max']):
            raise ValueError(f"حداکثر مقدار برای {meta['label']} برابر {meta['max']} است")
        return number, str(number)
    if meta['type'] == 'bool':
        lowered = value.lower()
        if lowered in {'1', 'on', 'true', 'yes', 'y', 'enable', 'enabled'}:
            return True, 'on'
        if lowered in {'0', 'off', 'false', 'no', 'n', 'disable', 'disabled'}:
            return False, 'off'
        raise ValueError('برای این گزینه فقط on/off یا yes/no بفرست')
    if meta['type'] == 'secret':
        if not value:
            raise ValueError('این مقدار نمی‌تواند خالی باشد')
        return value, 'configured'
    if not value and not meta.get('allow_empty'):
        raise ValueError('این مقدار نمی‌تواند خالی باشد')
    return value, value or '-'


def apply_setting_change(key: str, value: Any) -> str:
    meta = EDITABLE_SETTINGS[key]
    if key == 'cloudflare_api_token':
        CLOUDFLARE.store_token(str(value))
        return 'configured'
    config[key] = value
    if key == 'cloudflare_domain_name':
        config['cloudflare_zone_name'] = value
    persist_master_config()
    refresh_runtime_config()
    services = tuple(meta.get('services') or ())
    if services:
        schedule_service_restart(services)
    return setting_display_value(key)


async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plans = DB.list_plans(enabled_only=False)
    lines = [f"• {p['label']} | {p['traffic_gb']}GB | {p['days']} روز | {'فعال' if p['enabled'] else 'غیرفعال'}" for p in plans]
    await respond(update, list_text('پلن‌ها', lines), InlineKeyboardMarkup([[_menu_button('🏠 خانه', 'menu:home')]]))


async def add_server_ssh_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_ssh_wizard(context)
    set_ssh_wizard(context, {'step': 'name', 'data': {}})
    await send_temp(update, 'مرحله ۱ از ۵\n🆔 نام سرور جدید را بفرست. مثال: <code>ir1</code>')


def mark_server_stage(name: str, state: str, message: str) -> None:
    try:
        DB.update_server_stage(name, state, message[:500], now_iso())
    except Exception:
        LOGGER.exception('update_server_stage_failed server=%s state=%s', name, state)


def summarize_error(code: str, title: str, detail: str = '') -> str:
    base = f"❌ {title}\nError Code: <code>{code}</code>"
    if detail:
        base += f"\n{detail}"
    return base


def tail_file(path: str, lines: int = 20) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return 'log file not found'
    data = file_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    return '\n'.join(data[-lines:]) if data else 'log file is empty'


def server_logs_text(server_name: str) -> str:
    server = DB.get_server(server_name)
    if not server:
        return '❌ سرور پیدا نشد'
    errors = DB.list_error_events(limit=8, target_key=server_name)
    lines = [server_text(server), '', '<b>آخرین خطاهای مرتبط</b>']
    if not errors:
        lines.append('موردی ثبت نشده است.')
    else:
        for item in errors:
            lines.append(f"• {item['created_at']} | {item['code']} | {item['message'][:120]}")
    return '\n'.join(lines)


def xray_status_text(server_name: str) -> str:
    server = DB.get_server(server_name)
    if not server:
        return '❌ سرور پیدا نشد'
    try:
        client = server_client(server)
        health = client.health()['data']
        cfg = client.get('/config/summary').get('data', {})
        return (
            f"<b>Xray Status — {server_name}</b>\n"
            f"🔘 Server enabled: {'بله' if server.get('enabled') else 'خیر'}\n"
            f"💚 Health: {server.get('last_health_status') or 'unknown'}\n"
            f"⚙️ Xray active: {'بله' if health.get('xray_active') else 'خیر'}\n"
            f"📡 Public host: {cfg.get('public_host') or server.get('public_host') or '-'}\n"
            f"🔌 Simple port: {cfg.get('simple_port') or server.get('xray_port') or '-'}\n"
            f"🔐 Reality port: {cfg.get('reality_port') or server.get('reality_port') or '-'}\n"
            f"🚚 Transport mode: {cfg.get('transport_mode') or server.get('transport_mode') or '-'}\n"
            f"🧠 CPU: {health.get('cpu_percent', 0)}% | RAM: {health.get('memory_percent', 0)}% | Disk: {health.get('disk_percent', 0)}%"
        )
    except Exception as exc:
        code = record_error(DB, LOGGER, component='agent', target_type='server', target_key=server_name, message='xray status check failed', exc=exc)
        return summarize_error(code, f'خطا در وضعیت Xray سرور {server_name}')


def health_report_text() -> str:
    servers = DB.list_servers()
    if not servers:
        return '<b>گزارش سلامت</b>\n\nهیچ سروری ثبت نشده است.'
    lines = ['<b>گزارش سلامت سرورها</b>']
    for server in servers:
        icon = '🟢' if server.get('enabled') and (server.get('last_health_status') or '') == 'ok' else '🟠' if server.get('enabled') else '⚫️'
        lines.append(f"{icon} <b>{server['name']}</b> | state={server.get('provisioning_state') or '-'} | health={server.get('last_health_status') or '-'} | xray={'on' if server.get('xray_active') else 'off'}")
        lines.append(f"   CPU {server.get('cpu_percent', 0)}% | RAM {server.get('memory_percent', 0)}% | Disk {server.get('disk_percent', 0)}% | Users {server.get('user_count', 0)}")
    return '\n'.join(lines)

def user_text(user: Dict[str, Any]) -> str:
    link = build_vless_link(user)
    return (
        f"<b>کاربر: {user['username']}</b>\n"
        f"🖥 سرور: {user['server_name']}\n"
        f"🆔 UUID: <code>{user['uuid']}</code>\n"
        f"📦 حجم: {user['traffic_gb']} GB\n"
        f"📊 مصرف: {user['used_gb']} GB\n"
        f"📅 انقضا: {user['expire_date']}\n"
        f"💳 کریدیت: {user['credit_balance']}\n"
        f"🏷 پلن: {resolve_plan_label(user.get('plan') or '')}\n"
        f"📌 یادداشت: {user.get('notes') or '-'}\n"
        f"🔘 وضعیت: {'فعال' if user['is_active'] else 'غیرفعال'}\n\n"
        f"<code>{link}</code>"
    )


def server_text(server: Dict[str, Any]) -> str:
    return (
        f"<b>سرور: {server['name']}</b>\n"
        f"🌐 API: <code>{server['api_url']}</code>\n"
        f"📡 Public host: {server.get('public_host') or '-'}\n"
        f"🔌 Port: {server.get('xray_port') or '-'}\n"
        f"🚚 Transport: {server.get('transport_mode') or 'tcp'}\n"
        f"💚 Health: {server.get('last_health_status') or 'unknown'}\n"
        f"📝 Health msg: {server.get('last_health_message') or '-'}\n"
        f"⏰ Last check: {server.get('last_health_at') or '-'}\n"
        f"🧠 CPU: {server.get('cpu_percent', 0)}% | RAM: {server.get('memory_percent', 0)}% | Disk: {server.get('disk_percent', 0)}%\n"
        f"📈 Load: {server.get('load_1m', 0)} | 👥 Users: {server.get('user_count', 0)} | 🔄 Last sync: {server.get('last_sync_at') or '-'}\n"
        f"🧭 مرحله: {server.get('provisioning_state') or '-'}\n"
        f"💬 پیام مرحله: {server.get('provisioning_message') or '-'}\n"
        f"🔘 وضعیت: {'فعال' if server['enabled'] else 'غیرفعال'}"
    )

def list_text(title: str, lines: List[str]) -> str:
    body = '\n'.join(lines) if lines else 'موردی پیدا نشد.'
    return f"<b>{title}</b>\n\n{body}"


# ---------- Panel views ----------
async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_prompt(context)
    await respond(update, status_text(), main_menu_markup())


async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    users = DB.list_users()
    page_count = max(math.ceil(len(users) / PAGE_SIZE), 1)
    page = max(0, min(page, page_count - 1))
    start = page * PAGE_SIZE
    page_users = users[start:start + PAGE_SIZE]
    lines = [format_user_brief(u) for u in page_users]
    text = list_text(f'لیست کاربران — صفحه {page + 1}/{page_count}', lines)
    await respond(update, text, users_page_markup(users, page))


async def show_servers(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    servers = DB.list_servers()
    page_count = max(math.ceil(len(servers) / PAGE_SIZE), 1)
    page = max(0, min(page, page_count - 1))
    start = page * PAGE_SIZE
    page_servers = servers[start:start + PAGE_SIZE]
    lines = []
    for s in page_servers:
        status = s.get('last_health_status') or 'unknown'
        lines.append(f"• <b>{s['name']}</b> — {status} — {'enabled' if s['enabled'] else 'disabled'}")
    text = list_text(f'لیست سرورها — صفحه {page + 1}/{page_count}', lines)
    await respond(update, text, servers_page_markup(servers, page))


async def show_user(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str) -> None:
    user = DB.get_user(username)
    if not user:
        await send_temp(update, '❌ کاربر پیدا نشد.')
        return
    await respond(update, user_text(user), user_detail_markup(user))


async def show_server(update: Update, context: ContextTypes.DEFAULT_TYPE, server_id: int) -> None:
    server = DB.get_server_by_id(server_id)
    if not server:
        await send_temp(update, '❌ سرور پیدا نشد.')
        return
    await respond(update, server_text(server), server_detail_markup(server))


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '<b>راهنمای سریع</b>\n\n'
        '• ساخت کاربر از منوی دکمه‌ای به‌صورت مرحله‌به‌مرحله انجام می‌شود.\n'
        '• برای عملیات حساس مثل حذف/غیرفعال‌سازی، تأیید دومرحله‌ای با کد فعال است.\n'
        '• سطح دسترسی‌ها: مالک، ادمین، پشتیبان.\n\n'
        'دستورهای متنی اصلی:\n'
        '/start /panel /status /help\n'
        '/new_user <server> <name> <traffic> <days>\n'
        '/new_user <name> <traffic> <days>\n'
        '/list_users /list_servers /user_info <name>\n'
        '/list_admins /add_admin <chat_id> <owner|admin|support> /remove_admin <chat_id>\n'
        '/settings برای تغییر تنظیمات اصلی مستر\n'
        'یا از پنل ادمین‌ها و تنظیمات داخل ابزارها استفاده کن.\n'
        '/sync_usage /backup_now /send_backup\n'
        '/cleanup_expired /cleanup_quota\n\n'
        'برای لغو هر روند ورودی: /cancel'
    )
    await respond(update, text, InlineKeyboardMarkup([[InlineKeyboardButton('🏠 خانه', callback_data='menu:home')]]))


async def show_reports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    expired = DB.list_expired_active_users(today_utc())
    quota = DB.list_over_quota_active_users()
    lines = [
        f'⌛ کاربران منقضی فعال: {len(expired)}',
        f'📉 کاربران لب‌مرز/تمام حجم: {len(quota)}',
        f'🧾 آخرین لاگ‌ها: {len(DB.list_audits(5))}',
        'از دکمه‌ها برای عملیات گزارش و پاکسازی استفاده کن.',
    ]
    await respond(update, list_text('گزارش‌ها', lines), reports_menu_markup())


async def show_tools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    latest_backup = DB.latest_backup()
    lines = [
        '• ساخت بکاپ از مستر و نودها',
        '• ارسال آخرین بکاپ به تلگرام',
        '• خروجی CSV کاربران',
        '• بازگشت به داشبورد',
    ]
    if latest_backup:
        lines.append(f"آخرین بکاپ: {latest_backup['created_at']}")
    await respond(update, list_text('ابزارها', lines), tools_menu_markup())


# ---------- Commands ----------
@admin_only
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_home(update, context)


@admin_only
async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_home(update, context)


@admin_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_help(update, context)


@admin_only
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await respond(update, status_text(), main_menu_markup())


@role_required('owner')
async def add_server_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 3:
        set_prompt(context, 'add_server')
        await respond(update, 'فرمت سریع:\n<code>/add_server name https://host:port token</code>\n\nیا دکمه را بزن و متن را به شکل زیر بفرست:\n<code>name|https://host:port|token</code>', main_menu_markup())
        return
    result = do_add_server(*context.args)
    await send_temp(update, result)



def do_add_server(name: str, api_url: str, api_token: str) -> str:
    if not valid_server_name(name):
        return '❌ نام سرور نامعتبر است.'
    created_at = now_iso()
    existing = DB.get_server(name)
    DB.add_or_update_server(
        {
            'name': name,
            'api_url': api_url,
            'api_token': api_token,
            'public_host': existing.get('public_host', '') if existing else '',
            'host_mode': existing.get('host_mode', '') if existing else '',
            'xray_port': int(existing.get('xray_port') or 0) if existing else 0,
            'transport_mode': existing.get('transport_mode', 'tcp') if existing else 'tcp',
            'reality_server_name': existing.get('reality_server_name', '') if existing else '',
            'reality_public_key': existing.get('reality_public_key', '') if existing else '',
            'reality_short_id': existing.get('reality_short_id', '') if existing else '',
            'fingerprint': existing.get('fingerprint', 'chrome') if existing else 'chrome',
            'enabled': True,
            'last_health_status': existing.get('last_health_status', '') if existing else '',
            'last_health_message': existing.get('last_health_message', '') if existing else '',
            'last_health_at': existing.get('last_health_at', '') if existing else '',
            'provisioning_state': 'verifying',
            'provisioning_message': 'verifying agent health',
            'created_at': existing['created_at'] if existing else created_at,
            'updated_at': now_iso(),
        }
    )
    try:
        client = AgentClient(api_url, api_token, timeout=AGENT_TIMEOUT)
        health = client.health()['data']
        DB.add_or_update_server(
            {
                'name': name,
                'api_url': api_url,
                'api_token': api_token,
                'public_host': health.get('public_host', ''),
                'host_mode': health.get('host_mode', ''),
                'xray_port': int(health.get('simple_port') or health.get('xray_port') or 0),
                'reality_port': int(health.get('reality_port') or 0),
                'transport_mode': health.get('transport_mode', 'tcp'),
                'reality_server_name': health.get('reality_server_name', ''),
                'reality_public_key': health.get('reality_public_key', ''),
                'reality_short_id': health.get('reality_short_id', ''),
                'fingerprint': health.get('fingerprint', 'chrome'),
                'enabled': True,
                'last_health_status': 'ok',
                'last_health_message': '',
                'last_health_at': created_at,
                'xray_active': bool(health.get('xray_active', True)),
                'provisioning_state': 'healthy',
                'provisioning_message': 'agent verified successfully',
                'created_at': existing['created_at'] if existing else created_at,
                'updated_at': now_iso(),
            }
        )
        fresh_server = DB.get_server(name)
        for existing_user in DB.list_users_by_access_mode('all'):
            try:
                server_client(fresh_server).add_user(existing_user['username'], existing_user['uuid'])
            except Exception:
                LOGGER.exception('provision_all_mode_user_failed user=%s server=%s', existing_user['username'], name)
        audit('add_server', 'server', name, api_url)
        return f"✅ سرور ذخیره شد: {name} → {health.get('public_host')}:{health.get('xray_port')}"
    except Exception as exc:
        mark_server_stage(name, 'failed', str(exc))
        code = record_error(DB, LOGGER, component='agent', target_type='server', target_key=name, message='add server failed', exc=exc)
        return summarize_error(code, f'افزودن سرور {name} ناموفق بود')


@admin_only
async def list_servers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_servers(update, context, 0)


@admin_only
async def server_health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /server_health <name>')
        return
    try:
        _, health = refresh_server_metadata(context.args[0])
    except Exception as exc:
        await send_temp(update, f'❌ خطا در health check: {exc}')
        return
    await send_temp(update, list_text(f"سلامت سرور {context.args[0]}", [f'{k}: {v}' for k, v in health.items()]))


@role_required('admin')
async def new_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) not in (3, 4):
        set_prompt(context, 'create_user')
        await send_temp(update, 'برای ساخت کاربر این فرمت را بفرست:\n<code>server|username|traffic_gb|days</code>\nیا\n<code>username|traffic_gb|days</code>')
        return
    try:
        if len(context.args) == 4:
            server_name, username, traffic, days = context.args
            server = DB.get_server(server_name)
            if not server or not server.get('enabled'):
                raise ValueError('server not found or disabled')
        else:
            username, traffic, days = context.args
            server = preferred_server_for_quick_create()
        if not valid_username(username):
            raise ValueError('invalid username')
        user = create_user_on_server(server, username, int(traffic), int(days))
        await send_temp(update, f"✅ کاربر ساخته شد روی <b>{user['server_name']}</b>\n\n{user_text(user)}")
    except Exception as exc:
        await send_temp(update, f'❌ ساخت کاربر ناموفق بود: {exc}')


@admin_only
async def list_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_users(update, context, 0)


@admin_only
async def user_info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /user_info <username>')
        return
    await show_user(update, context, context.args[0])


@admin_only
async def search_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        set_prompt(context, 'search_users')
        await send_temp(update, 'عبارت جستجو را بفرست.')
        return
    users = DB.search_users(' '.join(context.args))
    await respond(update, list_text('نتیجه جستجو', [format_user_brief(u) for u in users[:30]]), InlineKeyboardMarkup([[InlineKeyboardButton('🏠 خانه', callback_data='menu:home')]]))


@admin_only
async def subscription_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /subscription <username>')
        return
    username = context.args[0]
    user = DB.get_user(username)
    if not user:
        await send_temp(update, '❌ کاربر پیدا نشد')
        return
    await send_temp(update, f"🔗 لینک ثابت سابسکریپشن: <code>{subscription_url_for_user(username)}</code>")


@role_required('admin')
async def set_access_all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /set_access_all <username>')
        return
    user = DB.get_user(context.args[0])
    if not user:
        await send_temp(update, '❌ کاربر پیدا نشد')
        return
    set_user_access_all(user)
    await send_temp(update, f"✅ دسترسی {user['username']} روی همه سرورها باز شد. <code>{subscription_url_for_user(user['username'])}</code>")


@role_required('admin')
async def set_access_selected_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await send_temp(update, 'فرمت درست: /set_access_selected <username> <server1,server2,...>')
        return
    username = context.args[0]
    names = [x.strip() for x in ' '.join(context.args[1:]).split(',') if x.strip()]
    user = DB.get_user(username)
    if not user:
        await send_temp(update, '❌ کاربر پیدا نشد')
        return
    set_user_access_selected(user, names)
    await send_temp(update, f"✅ دسترسی {username} روی سرورهای انتخابی تنظیم شد. <code>{subscription_url_for_user(username)}</code>")
@role_required('admin')
async def grant_server_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await send_temp(update, 'فرمت درست: /grant_server <username> <server>')
        return
    username, server_name = context.args
    user = DB.get_user(username)
    server = DB.get_server(server_name)
    if not user or not server:
        await send_temp(update, '❌ کاربر یا سرور پیدا نشد')
        return
    DB.set_user_access_mode(username, 'selected', now_iso())
    DB.grant_user_server_access(username, server_name, now_iso())
    try:
        server_client(server).add_user(username, user['uuid'])
    except Exception as exc:
        await send_temp(update, f'⚠️ دسترسی ثبت شد ولی افزودن روی سرور خطا داد: {exc}')
        return
    audit('grant_server', 'user', username, f'server={server_name}')
    await send_temp(update, f'✅ {server_name} به دسترسی‌های {username} اضافه شد.')


@role_required('admin')
async def revoke_server_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await send_temp(update, 'فرمت درست: /revoke_server <username> <server>')
        return
    username, server_name = context.args
    user = DB.get_user(username)
    server = DB.get_server(server_name)
    if not user or not server:
        await send_temp(update, '❌ کاربر یا سرور پیدا نشد')
        return
    DB.revoke_user_server_access(username, server_name)
    DB.set_user_access_mode(username, 'selected', now_iso())
    try:
        server_client(server).remove_user(username)
    except Exception:
        LOGGER.exception('revoke_server_remove_failed username=%s server=%s', username, server_name)
    audit('revoke_server', 'user', username, f'server={server_name}')
    await send_temp(update, f'✅ {server_name} از دسترسی‌های {username} حذف شد.')


@admin_only
async def list_access_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /list_access <username>')
        return
    username = context.args[0]
    user = DB.get_user(username)
    if not user:
        await send_temp(update, '❌ کاربر پیدا نشد')
        return
    servers = DB.list_user_access_servers(username, enabled_only=False)
    lines = [f"- {s['name']}" for s in servers] or ['- هیچ سروری ثبت نشده']
    await send_temp(update, list_text(f"دسترسی‌های {username} | mode={user.get('access_mode')}", lines))


@role_required('admin')
async def sync_usage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = sync_usage_once()
    audit('sync_usage', 'system', 'all', f'users={count}')
    await send_temp(update, f'✅ مصرف {count} کاربر همگام‌سازی شد.')


@admin_only
async def expired_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = DB.list_expired_active_users(today_utc())
    await respond(update, list_text('کاربران منقضی فعال', [format_user_brief(u) for u in users]), reports_menu_markup())


@admin_only
async def quota_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    users = DB.list_over_quota_active_users()
    await respond(update, list_text('کاربران تمام‌حجم فعال', [format_user_brief(u) for u in users]), reports_menu_markup())


@role_required('admin')
async def cleanup_expired_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = cleanup_expired_once()
    await send_temp(update, f'✅ {count} کاربر منقضی غیرفعال شد.')


@role_required('admin')
async def cleanup_quota_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    count = cleanup_quota_once()
    await send_temp(update, f'✅ {count} کاربر over-quota غیرفعال شد.')


@role_required('admin')
async def backup_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    meta = BACKUPS.create_backup(DB.list_servers())
    audit('backup_now', 'backup', os.path.basename(meta['path']), meta['checksum'])
    await send_temp(update, f"✅ بکاپ ساخته شد\n<code>{meta['path']}</code>")


@role_required('admin')
async def send_backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    latest = DB.latest_backup()
    if not latest or not os.path.exists(latest['path']):
        await send_temp(update, '❌ بکاپی پیدا نشد.')
        return
    with open(latest['path'], 'rb') as fh:
        await update.effective_message.reply_document(document=fh, filename=os.path.basename(latest['path']), caption='آخرین بکاپ')


@role_required('admin')
async def export_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    with tempfile.NamedTemporaryFile(prefix='users_', suffix='.csv', delete=False) as tmp:
        path = tmp.name
    export_users_csv(path, DB.list_users())
    with open(path, 'rb') as fh:
        await update.effective_message.reply_document(document=fh, filename='users.csv', caption='خروجی کاربران')
    os.remove(path)


@role_required('owner')
async def list_admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_admins(update, context)


@role_required('owner')
async def add_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 2:
        await send_temp(update, 'فرمت درست: /add_admin <chat_id> <owner|admin|support>')
        return
    chat_id, role = context.args[0].strip(), context.args[1].strip().lower()
    if role not in ROLE_LEVELS:
        await send_temp(update, 'نقش نامعتبر است. فقط owner یا admin یا support')
        return
    now = now_iso()
    existing = DB.get_admin(chat_id)
    created = existing['created_at'] if existing else now
    display_name = existing['display_name'] if existing else ''
    DB.upsert_admin(chat_id, role, display_name, created, now, True)
    audit('add_admin', 'admin', chat_id, role)
    await send_temp(update, f'✅ ادمین ذخیره شد: {chat_id} → {role_label(role)}')


@role_required('owner')
async def remove_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /remove_admin <chat_id>')
        return
    chat_id = context.args[0].strip()
    target = DB.get_admin(chat_id)
    if not target:
        await send_temp(update, '❌ ادمین پیدا نشد')
        return
    if target.get('role') == 'owner' and DB.count_admins_by_role('owner') <= 1:
        await send_temp(update, '❌ آخرین مالک را نمی‌توان حذف کرد')
        return
    DB.delete_admin(chat_id)
    audit('remove_admin', 'admin', chat_id, '')
    await send_temp(update, f'✅ ادمین حذف شد: {chat_id}')


@admin_only
async def list_plans_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_plans(update, context)


@role_required('owner')
async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_settings(update, context)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_prompt(context)
    clear_wizard(context)
    clear_confirmation(context)
    await send_temp(update, '✅ عملیات ورودی/تأیید لغو شد.')


# ---------- Callback actions ----------
@admin_only
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await safe_answer(query)
    data = query.data or ''
    try:
        if data == 'wizard:create_user':
            if await deny_if_not_admin(update, 'admin'):
                return
            await start_create_user_wizard(update, context)
            return
        if data == 'wizard:cancel':
            clear_wizard(context)
            clear_ssh_wizard(context)
            await show_home(update, context)
            return
        if data == 'tool:list_admins':
            if await deny_if_not_admin(update, 'owner'):
                return
            await show_admins(update, context)
            return
        if data == 'tool:settings':
            if await deny_if_not_admin(update, 'owner'):
                return
            await show_settings(update, context)
            return
        if data.startswith('setting:edit:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            key = data.split(':', 2)[2]
            meta = EDITABLE_SETTINGS.get(key)
            if not meta:
                await send_temp(update, '❌ تنظیم موردنظر پیدا نشد')
                return
            set_prompt(context, f'setting:{key}', '')
            sample = 'yes / no' if meta['type'] == 'bool' else 'value'
            await send_temp(update, f"مقدار جدید برای <b>{meta['label']}</b> را بفرست.\nمقدار فعلی: <code>{setting_display_value(key)}</code>\nنمونه: <code>{sample}</code>\nبرای لغو: /cancel")
            return
        if data.startswith('admin:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            await show_admin_detail(update, context, data.split(':', 1)[1])
            return
        if data.startswith('admin_add:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            role = data.split(':', 1)[1]
            set_prompt(context, f'add_admin_button:{role}', '')
            await send_temp(update, f'چت‌آیدی ادمین جدید با نقش {role_label(role)} را بفرست.')
            return
        if data.startswith('admin_role:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            _, chat_id, role = data.split(':', 2)
            target = DB.get_admin(chat_id)
            if not target:
                await send_temp(update, '❌ ادمین پیدا نشد')
                return
            if target.get('role') == 'owner' and role != 'owner' and DB.count_admins_by_role('owner') <= 1:
                await send_temp(update, '❌ آخرین مالک را نمی‌توان تنزل داد')
                return
            if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS.get(target.get('role') or '', 0):
                code = set_confirmation(context, 'admin_role', f'{chat_id}|{role}')
                await send_temp(update, f'🔐 تأیید دومرحله‌ای\nبرای تنزل نقش، کد <code>{code}</code> را ظرف ۳ دقیقه ارسال کن.\nبرای لغو: /cancel')
                return
            DB.set_admin_role(chat_id, role, now_iso())
            audit('set_admin_role', 'admin', chat_id, role)
            await show_admin_detail(update, context, chat_id)
            return
        if data.startswith('admin_enable:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            chat_id = data.split(':', 1)[1]
            DB.set_admin_enabled(chat_id, True, now_iso())
            audit('enable_admin', 'admin', chat_id, '')
            await show_admin_detail(update, context, chat_id)
            return
        if data.startswith('admin_disable:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            chat_id = data.split(':', 1)[1]
            target = DB.get_admin(chat_id)
            if not target:
                await send_temp(update, '❌ ادمین پیدا نشد')
                return
            if target.get('role') == 'owner' and DB.count_admins_by_role('owner') <= 1:
                await send_temp(update, '❌ آخرین مالک را نمی‌توان غیرفعال کرد')
                return
            code = set_confirmation(context, 'admin_disable', chat_id)
            await send_temp(update, f'🔐 تأیید دومرحله‌ای\nبرای غیرفعال‌سازی ادمین، کد <code>{code}</code> را ظرف ۳ دقیقه ارسال کن.\nبرای لغو: /cancel')
            return
        if data.startswith('admin_remove:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            chat_id = data.split(':', 1)[1]
            target = DB.get_admin(chat_id)
            if not target:
                await send_temp(update, '❌ ادمین پیدا نشد')
                return
            if target.get('role') == 'owner' and DB.count_admins_by_role('owner') <= 1:
                await send_temp(update, '❌ آخرین مالک را نمی‌توان حذف کرد')
                return
            code = set_confirmation(context, 'admin_remove', chat_id)
            await send_temp(update, f'🔐 تأیید دومرحله‌ای\nبرای حذف ادمین، کد <code>{code}</code> را ظرف ۳ دقیقه ارسال کن.\nبرای لغو: /cancel')
            return
        if data == 'wizard:add_server_ssh':
            if await deny_if_not_admin(update, 'owner'):
                return
            await add_server_ssh_cmd(update, context)
            return
        if data == 'wizard_server:auto':
            if await deny_if_not_admin(update, 'admin'):
                return
            generated = generate_username()
            set_wizard(context, {'step': 'username', 'data': {'server_mode': 'auto', 'username': generated}})
            await send_temp(update, f'مرحله ۲ از ۶\n👤 نام کاربری پیشنهادی آماده شد: <code>{generated}</code>\nبا دکمه‌ها ادامه بده.', reply_markup=wizard_username_markup(generated))
            return
        if data.startswith('wizard_server:id:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            server_id = int(data.split(':', 2)[2])
            server = DB.get_server_by_id(server_id)
            if not server or not server.get('enabled'):
                await send_temp(update, '❌ سرور معتبر نیست یا غیرفعال است.')
                return
            generated = generate_username()
            set_wizard(context, {'step': 'username', 'data': {'server_mode': 'manual', 'server_id': server_id, 'server_name': server['name'], 'username': generated}})
            await send_temp(update, f"مرحله ۲ از ۶\n👤 نام کاربری پیشنهادی برای سرور <b>{server['name']}</b>: <code>{generated}</code>", reply_markup=wizard_username_markup(generated))
            return
        if data == 'wizard_username:regen':
            if await deny_if_not_admin(update, 'admin'):
                return
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            if wizard.get('step') != 'username':
                await send_temp(update, 'ℹ️ الان در مرحله انتخاب نام نیستی.')
                return
            data_map['username'] = generate_username()
            set_wizard(context, {'step': 'username', 'data': data_map})
            await send_temp(update, f"🎲 نام جدید: <code>{data_map['username']}</code>", reply_markup=wizard_username_markup(data_map['username']))
            return
        if data == 'wizard_username:next':
            if await deny_if_not_admin(update, 'admin'):
                return
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            username = data_map.get('username') or generate_username()
            if DB.get_user(username):
                username = generate_username()
            data_map['username'] = username
            data_map.setdefault('traffic_gb', 50)
            set_wizard(context, {'step': 'traffic', 'data': data_map})
            await send_temp(update, f"مرحله ۳ از ۶\n📦 حجم کاربر را با دکمه انتخاب کن. مقدار فعلی: <b>{data_map['traffic_gb']} GB</b>", reply_markup=wizard_value_markup('traffic', int(data_map['traffic_gb'])))
            return
        if data.startswith('wizard_traffic:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            if wizard.get('step') != 'traffic':
                await send_temp(update, 'ℹ️ الان در مرحله حجم نیستی.')
                return
            _, mode, raw = data.split(':', 2)
            current = int(data_map.get('traffic_gb') or 50)
            if mode == 'set':
                current = int(raw)
            elif mode == 'delta':
                current = max(1, current + int(raw))
            elif mode == 'next':
                data_map['traffic_gb'] = current
                data_map.setdefault('days', 30)
                set_wizard(context, {'step': 'days', 'data': data_map})
                await send_temp(update, f"مرحله ۴ از ۶\n📅 مدت کاربر را با دکمه انتخاب کن. مقدار فعلی: <b>{data_map['days']} روز</b>", reply_markup=wizard_value_markup('days', int(data_map['days'])))
                return
            data_map['traffic_gb'] = current
            set_wizard(context, {'step': 'traffic', 'data': data_map})
            await send_temp(update, f"📦 حجم فعلی: <b>{current} GB</b>", reply_markup=wizard_value_markup('traffic', current))
            return
        if data.startswith('wizard_days:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            if wizard.get('step') != 'days':
                await send_temp(update, 'ℹ️ الان در مرحله زمان نیستی.')
                return
            _, mode, raw = data.split(':', 2)
            current = int(data_map.get('days') or 30)
            if mode == 'set':
                current = int(raw)
            elif mode == 'delta':
                current = max(1, current + int(raw))
            elif mode == 'next':
                data_map['days'] = current
                set_wizard(context, {'step': 'plan', 'data': data_map})
                await send_temp(update, 'مرحله ۵ از ۶\n🧾 پلن آماده را انتخاب کن یا از روی دکمه رد کن.', reply_markup=wizard_plan_markup())
                return
            data_map['days'] = current
            set_wizard(context, {'step': 'days', 'data': data_map})
            await send_temp(update, f"📅 مدت فعلی: <b>{current} روز</b>", reply_markup=wizard_value_markup('days', current))
            return
        if data.startswith('wizard_plan:set:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            plan = data.split(':', 2)[2]
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            data_map['plan'] = plan
            set_wizard(context, {'step': 'note', 'data': data_map})
            await send_temp(update, 'مرحله ۶ از ۶\n📝 یادداشت آماده را انتخاب کن یا رد کن.', reply_markup=wizard_note_markup())
            return
        if data.startswith('wizard_note:set:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            note = data.split(':', 2)[2]
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            data_map['notes'] = note
            set_wizard(context, {'step': 'confirm', 'data': data_map})
            await respond(update, wizard_summary_text(data_map), wizard_confirm_markup())
            return
        if data.startswith('wizard_skip:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            skip_step = data.split(':', 1)[1]
            wizard = current_wizard(context) or {}
            data_map = dict(wizard.get('data') or {})
            if skip_step == 'plan' and wizard.get('step') == 'plan':
                data_map['plan'] = ''
                set_wizard(context, {'step': 'note', 'data': data_map})
                await send_temp(update, 'مرحله ۶ از ۶\n📝 یادداشت آماده را انتخاب کن یا رد کن.', reply_markup=wizard_note_markup())
                return
            if skip_step == 'note' and wizard.get('step') == 'note':
                data_map['notes'] = ''
                set_wizard(context, {'step': 'confirm', 'data': data_map})
                await respond(update, wizard_summary_text(data_map), wizard_confirm_markup())
                return
            await send_temp(update, 'ℹ️ این مرحله قابل رد کردن نیست.')
            return
        if data == 'wizard_confirm:create':
            if await deny_if_not_admin(update, 'admin'):
                return
            wizard = current_wizard(context) or {}
            data_map = wizard.get('data') or {}
            if wizard.get('step') != 'confirm':
                await send_temp(update, 'ℹ️ فرایند ساخت کاربر کامل نشده است.')
                return
            if data_map.get('server_mode') == 'manual':
                server = DB.get_server_by_id(int(data_map['server_id']))
                if not server or not server.get('enabled'):
                    raise ValueError('server not found or disabled')
            else:
                server = preferred_server_for_quick_create()
            user = create_user_on_server(
                server,
                data_map['username'],
                int(data_map['traffic_gb']),
                int(data_map['days']),
                data_map.get('notes', ''),
                data_map.get('plan', ''),
            )
            clear_wizard(context)
            await send_temp(update, f"✅ کاربر ساخته شد روی <b>{user['server_name']}</b>")
            await show_user(update, context, user['username'])
            return
        if data.startswith('act:confirm_sensitive:'):
            parts = data.split(':')
            action = parts[2]
            subject = ':'.join(parts[3:])
            needed = 'owner' if action in ('remove_server', 'disable_server') else 'admin'
            if await deny_if_not_admin(update, needed):
                return
            code = set_confirmation(context, action, subject)
            await send_temp(update, f'مرحله ۲ تأیید\nبرای انجام عملیات حساس، کد <code>{code}</code> را ظرف ۳ دقیقه ارسال کن.\nبرای لغو: /cancel')
            return
        if data == 'menu:home':
            await show_home(update, context)
        elif data.startswith('menu:users:'):
            await show_users(update, context, int(data.split(':')[2]))
        elif data.startswith('menu:servers:'):
            await show_servers(update, context, int(data.split(':')[2]))
        elif data == 'menu:reports':
            await show_reports(update, context)
        elif data == 'menu:tools':
            await show_tools(update, context)
        elif data == 'menu:help':
            await show_help(update, context)
        elif data.startswith('user:'):
            await show_user(update, context, data.split(':', 1)[1])
        elif data.startswith('server:'):
            await show_server(update, context, int(data.split(':', 1)[1]))
        elif data.startswith('act:prompt:'):
            parts = data.split(':')
            action = parts[2]
            subject = parts[3] if len(parts) > 3 else ''
            if action in {'renew','set_traffic','add_traffic','add_credit','take_credit','set_plan','set_note'} and await deny_if_not_admin(update, 'admin'):
                return
            set_prompt(context, action, subject)
            prompt_map = {
                'create_user': 'متن را بفرست:\n<code>server|username|traffic_gb|days</code>\nیا\n<code>username|traffic_gb|days</code>',
                'add_server': 'متن را بفرست:\n<code>name|https://host:port|token</code>',
                'search_users': 'عبارت جستجو را بفرست.',
                'renew': f'برای کاربر <b>{subject}</b> فقط تعداد روز را بفرست. مثال: <code>30</code>',
                'set_traffic': f'برای کاربر <b>{subject}</b> حجم جدید را بفرست. مثال: <code>100</code>',
                'add_traffic': f'برای کاربر <b>{subject}</b> مقدار حجم اضافه را بفرست. مثال: <code>20</code>',
                'add_credit': f'برای کاربر <b>{subject}</b> مقدار کریدیت را بفرست. مثال: <code>500</code>',
                'take_credit': f'برای کاربر <b>{subject}</b> مقدار کریدیت قابل کسر را بفرست. مثال: <code>200</code>',
                'set_note': f'یادداشت جدید کاربر <b>{subject}</b> را بفرست.',
                'set_plan': f'نام پلن جدید برای کاربر <b>{subject}</b> را بفرست.',
                'add_admin_button': 'چت‌آیدی را بفرست.',
            }
            await send_temp(update, prompt_map.get(action.split(':', 1)[0], 'ورودی موردنیاز را بفرست.'))
        elif data.startswith('act:link:'):
            username = data.split(':', 2)[2]
            user = DB.get_user(username)
            if user:
                await send_temp(update, f"<code>{build_vless_link(user)}</code>")
        elif data.startswith('act:qr:'):
            username = data.split(':', 2)[2]
            user = DB.get_user(username)
            if user:
                path = write_qr_file(build_vless_link(user), os.path.join(config['qr_dir'], f'{username}.png'))
                with open(path, 'rb') as fh:
                    await query.message.reply_photo(photo=fh, caption=f'QR کاربر {username}')
        elif data.startswith('act:disable:'):
            username = data.split(':', 2)[2]
            user = DB.get_user(username)
            if user:
                disable_user_on_server(user)
                audit('disable_user', 'user', username, f"server={user['server_name']}")
                await show_user(update, context, username)
        elif data.startswith('act:enable:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            username = data.split(':', 2)[2]
            user = DB.get_user(username)
            if user:
                enable_user_on_server(user)
                audit('enable_user', 'user', username, f"server={user['server_name']}")
                await show_user(update, context, username)
        elif data.startswith('act:reset_usage:'):
            if await deny_if_not_admin(update, 'admin'):
                return
            username = data.split(':', 2)[2]
            DB.reset_user_usage_baseline(username, now_iso())
            audit('reset_usage', 'user', username, '')
            await show_user(update, context, username)
        elif data.startswith('act:server_health:'):
            server_id = int(data.split(':', 2)[2])
            server = DB.get_server_by_id(server_id)
            if server:
                try:
                    refresh_server_metadata(server['name'])
                except Exception:
                    pass
                await show_server(update, context, server_id)
        elif data.startswith('act:enable_server:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            server_id = int(data.split(':', 2)[2])
            server = DB.get_server_by_id(server_id)
            if server:
                DB.set_server_enabled(server['name'], True, now_iso())
                audit('enable_server', 'server', server['name'], '')
                await show_server(update, context, server_id)
        elif data.startswith('act:disable_server:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            server_id = int(data.split(':', 2)[2])
            server = DB.get_server_by_id(server_id)
            if server:
                DB.set_server_enabled(server['name'], False, now_iso())
                audit('disable_server', 'server', server['name'], '')
                await show_server(update, context, server_id)
        elif data.startswith('act:remove_server:'):
            if await deny_if_not_admin(update, 'owner'):
                return
            server_id = int(data.split(':', 2)[2])
            server = DB.get_server_by_id(server_id)
            if server:
                prepare_server_delete(server)
                audit('remove_server', 'server', server['name'], '')
            await show_servers(update, context, 0)
        elif data.startswith('act:server_users:'):
            server_id = int(data.split(':', 2)[2])
            server = DB.get_server_by_id(server_id)
            if server:
                users = DB.list_users(server['name'])
                await respond(update, list_text(f"کاربران سرور {server['name']}", [format_user_brief(u) for u in users]), InlineKeyboardMarkup([[InlineKeyboardButton('↩️ برگشت', callback_data=f'server:{server_id}')]]))
        elif data == 'report:expired':
            await expired_users_cmd(update, context)
        elif data == 'report:quota':
            await quota_users_cmd(update, context)
        elif data == 'report:sync_usage':
            await sync_usage_cmd(update, context)
        elif data == 'report:cleanup':
            count1 = cleanup_expired_once()
            count2 = cleanup_quota_once()
            await send_temp(update, f'✅ پاکسازی انجام شد. منقضی: {count1} | حجم‌تمام: {count2}')
        elif data == 'report:audits':
            audits = DB.list_audits(20)
            lines = [f"• {a['created_at']} | {a['action']} | {a['target_key']}" for a in audits]
            await respond(update, list_text('آخرین لاگ عملیات', lines), reports_menu_markup())
        elif data == 'tool:backup_now':
            await backup_now_cmd(update, context)
        elif data == 'tool:send_backup':
            await send_backup_cmd(update, context)
        elif data == 'tool:export_users':
            await export_users_cmd(update, context)
        elif data == 'tool:status':
            await status_cmd(update, context)
        else:
            await send_temp(update, 'ℹ️ این دکمه هنوز عملیات مشخصی ندارد.')
    except Exception as exc:
        LOGGER.exception('callback_router_failed data=%s', data)
        await send_temp(update, f'❌ خطا: {exc}')


# ---------- Text prompt processor ----------
@admin_only
async def prompt_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or '').strip()

    pending_confirm = current_confirmation(context)
    if pending_confirm:
        if time.time() > float(pending_confirm.get('expires_at', 0)):
            clear_confirmation(context)
            await send_temp(update, '⌛ زمان تأیید به پایان رسید. دوباره از دکمه عملیات استفاده کن.')
            return
        if text != pending_confirm.get('code'):
            await send_temp(update, '❌ کد تأیید نادرست است. برای لغو: /cancel')
            return
        action = pending_confirm.get('action', '')
        subject = pending_confirm.get('subject', '')
        clear_confirmation(context)
        try:
            if action == 'delete':
                user = DB.get_user(subject)
                if user:
                    delete_user_everywhere(user)
                    audit('delete_user', 'user', subject, 'two_step')
                await show_users(update, context, 0)
                return
            if action == 'disable':
                user = DB.get_user(subject)
                if not user:
                    raise ValueError('user not found')
                disable_user_on_server(user)
                audit('disable_user', 'user', subject, 'two_step')
                await show_user(update, context, subject)
                return
            if action == 'disable_server':
                server = DB.get_server_by_id(int(subject))
                if not server:
                    raise ValueError('server not found')
                DB.set_server_enabled(server['name'], False, now_iso())
                audit('disable_server', 'server', server['name'], 'two_step')
                await show_server(update, context, int(subject))
                return
            if action == 'remove_server':
                server = DB.get_server_by_id(int(subject))
                if not server:
                    raise ValueError('server not found')
                prepare_server_delete(server)
                audit('remove_server', 'server', server['name'], 'two_step')
                await show_servers(update, context, 0)
                return
            raise ValueError('unsupported confirmation action')
        except Exception as exc:
            await send_temp(update, f'❌ عملیات حساس ناموفق بود: {exc}')
            return

    wizard = current_wizard(context)
    if wizard:
        step = wizard.get('step')
        data = dict(wizard.get('data') or {})
        try:
            if step == 'username':
                if not valid_username(text):
                    raise ValueError('نام کاربری نامعتبر است')
                if DB.get_user(text):
                    raise ValueError('این نام کاربری از قبل وجود دارد')
                data['username'] = text
                set_wizard(context, {'step': 'traffic', 'data': data})
                await send_temp(update, 'مرحله ۳ از ۴\nحجم را به گیگابایت بفرست. مثال: 50')
                return
            if step == 'traffic':
                traffic = int(text)
                if traffic <= 0:
                    raise ValueError('حجم باید بزرگ‌تر از صفر باشد')
                data['traffic_gb'] = traffic
                set_wizard(context, {'step': 'days', 'data': data})
                await send_temp(update, 'مرحله ۴ از ۶\nمدت را به روز بفرست. مثال: 30')
                return
            if step == 'days':
                days = int(text)
                if days <= 0:
                    raise ValueError('روز باید بزرگ‌تر از صفر باشد')
                data['days'] = days
                set_wizard(context, {'step': 'plan', 'data': data})
                await send_temp(update, 'مرحله ۵ از ۶\nاگر خواستی نام پلن را بفرست، یا روی «رد کردن» بزن.', reply_markup=wizard_skip_markup('plan'))
                return
            if step == 'plan':
                data['plan'] = text
                set_wizard(context, {'step': 'note', 'data': data})
                await send_temp(update, 'مرحله ۶ از ۶\nاگر خواستی یادداشت کاربر را بفرست، یا روی «رد کردن» بزن.', reply_markup=wizard_skip_markup('note'))
                return
            if step == 'note':
                data['notes'] = text
                set_wizard(context, {'step': 'confirm', 'data': data})
                await respond(update, wizard_summary_text(data), wizard_confirm_markup())
                return
        except Exception as exc:
            await send_temp(update, f'❌ ورودی مرحله‌ای نامعتبر بود: {exc}\nبرای لغو: /cancel')
            return

    ssh_wizard = current_ssh_wizard(context)
    if ssh_wizard:
        step = ssh_wizard.get('step')
        data = dict(ssh_wizard.get('data') or {})
        try:
            if step == 'name':
                if not valid_server_name(text):
                    raise ValueError('نام سرور نامعتبر است')
                data['name'] = text
                set_ssh_wizard(context, {'step': 'host', 'data': data})
                await send_temp(update, 'مرحله ۲ از ۵\n🌐 IP یا دامنه SSH سرور را بفرست.')
                return
            if step == 'host':
                if not text:
                    raise ValueError('آدرس سرور لازم است')
                data['host'] = text
                set_ssh_wizard(context, {'step': 'port', 'data': data})
                await send_temp(update, 'مرحله ۳ از ۵\n🔌 پورت SSH را بفرست. مثال: <code>22</code>')
                return
            if step == 'port':
                port = int(text)
                if port <= 0 or port > 65535:
                    raise ValueError('پورت معتبر نیست')
                data['ssh_port'] = port
                set_ssh_wizard(context, {'step': 'username', 'data': data})
                await send_temp(update, 'مرحله ۴ از ۵\n👤 نام کاربری SSH را بفرست. مثال: <code>root</code>')
                return
            if step == 'username':
                if not text:
                    raise ValueError('نام کاربری SSH لازم است')
                data['ssh_username'] = text
                set_ssh_wizard(context, {'step': 'password', 'data': data})
                await send_temp(update, 'مرحله ۵ از ۵\n🔐 پسورد SSH را بفرست. این پسورد ذخیره نمی‌شود و فقط برای نصب Agent استفاده می‌شود.')
                return
            if step == 'password':
                if not text:
                    raise ValueError('پسورد SSH لازم است')
                data['ssh_password'] = text
                clear_ssh_wizard(context)
                await send_temp(update, f"⏳ در حال اتصال و نصب Agent روی <b>{data['name']}</b> ...\nاین کار ممکن است ۱ تا ۵ دقیقه طول بکشد.")
                result = await asyncio.to_thread(
                    do_add_server_via_ssh,
                    data['name'],
                    data['host'],
                    int(data['ssh_port']),
                    data['ssh_username'],
                    data['ssh_password'],
                )
                await send_temp(update, result)
                await show_servers(update, context, 0)
                return
        except (ProvisionError, ValueError) as exc:
            await send_temp(update, f'❌ افزودن خودکار سرور ناموفق بود: {exc}\nبرای لغو: /cancel')
            return
        except Exception as exc:
            code = record_error(DB, LOGGER, component='provisioner', target_type='server', target_key=data.get('name',''), message='ssh wizard failed', exc=exc)
            await send_temp(update, summarize_error(code, 'خطای پیش‌بینی‌نشده در نصب خودکار', 'برای لغو: /cancel'))
            return

    pending = current_prompt(context)
    if not pending:
        return
    action = pending.get('action', '')
    subject = pending.get('subject', '')
    try:
        if action == 'create_user':
            parts = [p.strip() for p in text.split('|')]
            if len(parts) == 4:
                server_name, username, traffic, days = parts
                server = DB.get_server(server_name)
                if not server or not server.get('enabled'):
                    raise ValueError('server not found or disabled')
            elif len(parts) == 3:
                username, traffic, days = parts
                server = preferred_server_for_quick_create()
            else:
                raise ValueError('format must be server|username|traffic|days or username|traffic|days')
            if not valid_username(username):
                raise ValueError('invalid username')
            user = create_user_on_server(server, username, int(traffic), int(days), '', '')
            clear_prompt(context)
            await send_temp(update, f"✅ کاربر ساخته شد روی <b>{user['server_name']}</b>")
            await show_user(update, context, user['username'])
            return

        if action == 'add_server':
            parts = [p.strip() for p in text.split('|')]
            if len(parts) != 3:
                raise ValueError('format must be name|api_url|api_token')
            result = do_add_server(parts[0], parts[1], parts[2])
            clear_prompt(context)
            await send_temp(update, result)
            await show_servers(update, context, 0)
            return

        if action.startswith('add_admin_button:'):
            role = action.split(':', 1)[1]
            chat_id = text.strip()
            if role not in ROLE_LEVELS:
                raise ValueError('invalid role')
            if not chat_id:
                raise ValueError('chat id is required')
            now = now_iso()
            existing = DB.get_admin(chat_id)
            created = existing['created_at'] if existing else now
            display_name = existing['display_name'] if existing else ''
            DB.upsert_admin(chat_id, role, display_name, created, now, True)
            audit('add_admin', 'admin', chat_id, f'button:{role}')
            clear_prompt(context)
            await send_temp(update, f'✅ ادمین ذخیره شد: {chat_id} → {role_label(role)}')
            await show_admins(update, context)
            return

        if action == 'search_users':
            clear_prompt(context)
            users = DB.search_users(text)
            await respond(update, list_text('نتیجه جستجو', [format_user_brief(u) for u in users[:30]]), InlineKeyboardMarkup([[InlineKeyboardButton('🏠 خانه', callback_data='menu:home')]]))
            return

        if action.startswith('setting:'):
            key = action.split(':', 1)[1]
            if key not in EDITABLE_SETTINGS:
                raise ValueError('setting not found')
            value, display = parse_setting_value(key, text)
            clear_prompt(context)
            apply_setting_change(key, value)
            audit('update_setting', 'config', key, display)
            await send_temp(update, f'✅ تنظیم ذخیره شد: <b>{EDITABLE_SETTINGS[key]["label"]}</b> → <code>{display}</code>')
            await show_settings(update, context)
            return

        user = DB.get_user(subject)
        if not user:
            raise ValueError('user not found')

        if action == 'renew':
            days = int(text)
            DB.set_expire(subject, add_days(user['expire_date'], days), now_iso())
            audit('renew_user', 'user', subject, f'days={days}')
        elif action == 'set_traffic':
            DB.set_traffic(subject, int(text), now_iso())
            audit('set_traffic', 'user', subject, text)
        elif action == 'add_traffic':
            DB.add_traffic(subject, int(text), now_iso())
            audit('add_traffic', 'user', subject, text)
        elif action == 'add_credit':
            DB.add_credit(subject, int(text), now_iso())
            audit('add_credit', 'user', subject, text)
        elif action == 'take_credit':
            DB.take_credit(subject, int(text), now_iso())
            audit('take_credit', 'user', subject, text)
        elif action == 'set_note':
            DB.update_user_notes(subject, text, user.get('plan') or '', now_iso())
            audit('set_note', 'user', subject, text)
        elif action == 'set_plan':
            DB.update_user_notes(subject, user.get('notes') or '', text, now_iso())
            audit('set_plan', 'user', subject, text)
        else:
            raise ValueError('unsupported action')

        clear_prompt(context)
        await show_user(update, context, subject)
    except Exception as exc:
        await send_temp(update, f'❌ ورودی نامعتبر یا عملیات ناموفق بود: {exc}\nبرای لغو: /cancel')




@admin_only
async def last_errors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    limit = 10
    if context.args:
        try:
            limit = max(1, min(int(context.args[0]), 50))
        except ValueError:
            pass
    rows = DB.list_error_events(limit=limit)
    if not rows:
        await send_temp(update, '✅ خطای ثبت‌شده‌ای پیدا نشد.')
        return
    lines = [f"• {row['created_at']} | <code>{row['code']}</code> | {row['component']} | {row['message'][:120]}" for row in rows]
    await send_temp(update, list_text('آخرین خطاها', lines))


@admin_only
async def health_report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_temp(update, health_report_text())


@admin_only
async def xray_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /xray_status <server>')
        return
    await send_temp(update, xray_status_text(context.args[0]))


@admin_only
async def server_logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) != 1:
        await send_temp(update, 'فرمت درست: /server_logs <server>')
        return
    await send_temp(update, server_logs_text(context.args[0]))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    record_error(DB, LOGGER, component='bot', target_type='telegram', target_key='', message='telegram handler error', exc=context.error if isinstance(context.error, Exception) else Exception(str(context.error)))


def main() -> None:
    bootstrap_admins()
    application = Application.builder().token(config['bot_token']).build()

    application.add_handler(CommandHandler(['start', 'panel'], start_cmd))
    application.add_handler(CommandHandler('help', help_cmd))
    application.add_handler(CommandHandler('status', status_cmd))
    application.add_handler(CommandHandler('add_server', add_server_cmd))
    application.add_handler(CommandHandler('add_server_ssh', add_server_ssh_cmd))
    application.add_handler(CommandHandler('dns_refresh_server', dns_refresh_server_cmd))
    application.add_handler(CommandHandler('list_servers', list_servers_cmd))
    application.add_handler(CommandHandler('server_health', server_health_cmd))
    application.add_handler(CommandHandler('server_profiles', server_profiles_cmd))
    application.add_handler(CommandHandler('new_user', new_user_cmd))
    application.add_handler(CommandHandler('subscription', subscription_cmd))
    application.add_handler(CommandHandler('set_access_all', set_access_all_cmd))
    application.add_handler(CommandHandler('set_access_selected', set_access_selected_cmd))
    application.add_handler(CommandHandler('grant_server', grant_server_cmd))
    application.add_handler(CommandHandler('revoke_server', revoke_server_cmd))
    application.add_handler(CommandHandler('list_access', list_access_cmd))
    application.add_handler(CommandHandler('list_users', list_users_cmd))
    application.add_handler(CommandHandler('user_info', user_info_cmd))
    application.add_handler(CommandHandler('search_users', search_users_cmd))
    application.add_handler(CommandHandler('sync_usage', sync_usage_cmd))
    application.add_handler(CommandHandler('expired_users', expired_users_cmd))
    application.add_handler(CommandHandler('quota_users', quota_users_cmd))
    application.add_handler(CommandHandler('cleanup_expired', cleanup_expired_cmd))
    application.add_handler(CommandHandler('cleanup_quota', cleanup_quota_cmd))
    application.add_handler(CommandHandler('backup_now', backup_now_cmd))
    application.add_handler(CommandHandler('send_backup', send_backup_cmd))
    application.add_handler(CommandHandler('export_users', export_users_cmd))
    application.add_handler(CommandHandler('last_errors', last_errors_cmd))
    application.add_handler(CommandHandler('health_report', health_report_cmd))
    application.add_handler(CommandHandler('xray_status', xray_status_cmd))
    application.add_handler(CommandHandler('server_logs', server_logs_cmd))
    application.add_handler(CommandHandler('list_admins', list_admins_cmd))
    application.add_handler(CommandHandler('list_plans', list_plans_cmd))
    application.add_handler(CommandHandler('settings', settings_cmd))
    application.add_handler(CommandHandler('add_admin', add_admin_cmd))
    application.add_handler(CommandHandler('remove_admin', remove_admin_cmd))
    application.add_handler(CommandHandler('cancel', cancel_cmd))

    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, prompt_text_handler))
    application.add_error_handler(error_handler)

    LOGGER.info('bot_started version=%s admins=%s', config.get('package_version', 'unknown'), ','.join(sorted(ADMIN_IDS)))
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
