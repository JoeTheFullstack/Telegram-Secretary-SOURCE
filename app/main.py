"""Entry point: wires everything and runs the polling loop. No business logic here."""
from __future__ import annotations

import logging
import sqlite3
import time

from app.adapters.llm import LLMClient
from app.adapters.telegram import TelegramClient, TelegramError, parse_update
from app.config import MIGRATIONS_DIR, Config, load_config
from app.core.customer_flow import Reply
from app.core.router import Router
from app.infra.db import connect, get_kv, set_kv
from app.infra.migrations import run_migrations

log = logging.getLogger("secretary")
OFFSET_KEY = "telegram_offset"
ERROR_REPLY = "خطای داخلی رخ داد. لطفاً دوباره تلاش کن."


def build_router(cfg: Config, conn: sqlite3.Connection, llm) -> Router:
    return Router(conn, llm, owner_ids=cfg.owner_ids)


def process_update(update: dict, router: Router, tg: TelegramClient) -> None:
    inc = parse_update(update)
    if inc is None:
        return
    if inc.callback_id:
        try:
            tg.answer_callback(inc.callback_id)
        except TelegramError as e:
            log.warning("answer_callback failed: %s", e)
    try:
        replies = router.handle(inc.telegram_id, inc.display_name, inc.text, inc.media)
    except Exception:
        log.exception("handler crashed (update %s)", inc.update_id)
        replies = [Reply(ERROR_REPLY)]
    for r in replies:
        try:
            if r.text:
                tg.send_message(inc.chat_id, r.text, r.buttons)
            if r.media:
                tg.send_media(inc.chat_id, r.media)
        except TelegramError as e:
            log.error("send failed: %s", e)


def run(config_path: str = "") -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(config_path)
    conn = connect(cfg.db_path)
    applied = run_migrations(conn, MIGRATIONS_DIR)
    if applied:
        log.info("applied migrations: %s", ", ".join(applied))
    llm = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, cfg.llm_timeout)
    tg = TelegramClient(cfg.telegram_token, cfg.telegram_proxy)
    router = build_router(cfg, conn, llm)

    offset = int(get_kv(conn, OFFSET_KEY) or 0)
    log.info("bot started, offset=%s", offset)
    while True:
        try:
            updates = tg.get_updates(offset)
        except TelegramError as e:
            log.warning("getUpdates failed: %s", e)
            time.sleep(5)
            continue
        for update in updates:
            process_update(update, router, tg)
            offset = update["update_id"] + 1          # always advance: no poison-update loops
            set_kv(conn, OFFSET_KEY, str(offset))


if __name__ == "__main__":
    run()
