
from __future__ import annotations

import secrets
import traceback
from typing import Optional

COMPONENT_PREFIX = {
    'bot': 'BOT',
    'scheduler': 'SCH',
    'provisioner': 'PRV',
    'cloudflare': 'CF',
    'agent': 'AGT',
    'subscription': 'SUB',
    'db': 'DB',
    'system': 'SYS',
}


def make_error_code(component: str) -> str:
    prefix = COMPONENT_PREFIX.get((component or 'system').lower(), 'SYS')
    return f"ERR-{prefix}-{secrets.token_hex(3).upper()}"


def record_error(db, logger, *, component: str, target_type: str = '', target_key: str = '', message: str = '', exc: Optional[Exception] = None) -> str:
    code = make_error_code(component)
    trace = ''
    if exc is not None:
        trace = traceback.format_exc()
        logger.exception('%s %s', code, message or str(exc))
        final_message = message or str(exc)
    else:
        logger.error('%s %s', code, message)
        final_message = message
    try:
        db.add_error_event(code, component, target_type, target_key, final_message, trace, __import__('datetime').datetime.utcnow().isoformat())
    except Exception:
        logger.exception('failed_to_store_error_event code=%s', code)
    return code
