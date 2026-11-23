"""Console chat for trying the bot WITHOUT Telegram.

  python -m app.cli --user 1 --owner            # you are the owner (can register customers)
  python -m app.cli --user 2                    # you are a customer (denied)
  python -m app.cli --user 1 --owner --offline  # no LLM: step-by-step fallback questions
Type a button number to press it. Ctrl+C to quit.
"""
from __future__ import annotations

import argparse
import sys

from app.adapters.llm import LLMClient, OfflineLLM
from app.config import MIGRATIONS_DIR, ROOT, load_config
from app.core.router import Router
from app.infra.db import connect
from app.infra.migrations import run_migrations


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", type=int, default=1, help="fake Telegram id")
    ap.add_argument("--owner", action="store_true", help="treat this user as owner")
    ap.add_argument("--offline", action="store_true", help="do not call any LLM")
    ap.add_argument("--db", default=str(ROOT / "data" / "dev.db"))
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    conn = connect(args.db)
    run_migrations(conn, MIGRATIONS_DIR)
    llm = OfflineLLM()
    if not args.offline:
        try:
            cfg = load_config()
            llm = LLMClient(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, cfg.llm_timeout)
        except (OSError, KeyError):
            print("(no config/config.json -> offline mode)")
    router = Router(conn, llm, owner_ids=[args.user] if args.owner else [])

    buttons = []
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.isdigit() and 1 <= int(text) <= len(buttons):
            text = buttons[int(text) - 1][1]
        buttons = []
        for r in router.handle(args.user, f"user{args.user}", text):
            print(f"bot> {r.text}")
            for row in r.buttons or []:
                for label, data in row:
                    buttons.append((label, data))
                    print(f"      [{len(buttons)}] {label}")


if __name__ == "__main__":
    main()
