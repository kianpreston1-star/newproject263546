"""Optional phone alerts through a Telegram bot."""
from __future__ import annotations

import logging

import requests

from .config import NotifyConfig

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: NotifyConfig):
        self.token = cfg.telegram_bot_token
        self.chat_id = cfg.telegram_chat_id

    def send(self, text: str) -> None:
        log.info(text)
        if not (self.token and self.chat_id):
            return
        try:
            requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          json={"chat_id": self.chat_id, "text": f"tradebot: {text}"}, timeout=10).raise_for_status()
        except requests.RequestException as e:  # the message would contain the URL, which holds the bot token
            log.warning("Couldn't send the Telegram alert (%s)", type(e).__name__)
