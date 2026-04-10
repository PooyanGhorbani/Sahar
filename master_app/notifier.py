from __future__ import annotations

from typing import Iterable, Optional

from utils import send_telegram_document, send_telegram_message


class Notifier:
    def __init__(self, bot_token: str, admin_ids: Iterable[str]):
        self.bot_token = bot_token
        self.admin_ids = list(admin_ids)

    def message(self, text: str) -> None:
        send_telegram_message(self.bot_token, self.admin_ids, text)

    def document(self, path: str, caption: Optional[str] = None) -> None:
        send_telegram_document(self.bot_token, self.admin_ids, path, caption)
