
from __future__ import annotations
import logging, os
from cloudflare_manager import CloudflareManager
from db import Database
from utils import load_config, setup_logging
CONFIG_PATH = os.path.expandvars(os.environ.get('SAHAR_CONFIG', '/opt/sahar-master/data/config.json'))
API_TOKEN = os.environ.get('CF_API_TOKEN', '')
def main() -> int:
    config = load_config(CONFIG_PATH)
    setup_logging(config['log_path'])
    db = Database(config['database_path'])
    cf = CloudflareManager(config, db)
    if not config.get('cloudflare_enabled') or not API_TOKEN:
        return 0
    cf.store_token(API_TOKEN)
    cf.resolve_zone_id()
    logging.getLogger('bootstrap_cloudflare').info('cloudflare bootstrap completed')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
