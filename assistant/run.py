from __future__ import annotations

import os
import time
from pathlib import Path

from bot import Controller, MAIN_KB
from core import Store, parse_admins
from telegram_api import TelegramAPI


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admins = parse_admins(os.getenv("ADMIN_IDS"))
    db_path = os.getenv("DB_PATH", "data/assistant.db")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing. Use simulate.py before Telegram is configured.")
    if len(admins) != 2:
        raise SystemExit("ADMIN_IDS must contain exactly two numeric Telegram user IDs.")

    store = Store(db_path)
    ctl = Controller(store, admins)
    tg = TelegramAPI(token)
    offset = None
    failures = 0

    while True:
        try:
            for update in tg.get_updates(offset=offset, timeout=30):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    q = update["callback_query"]
                    uid = int(q["from"]["id"])
                    if uid not in admins:
                        tg.answer_callback(q["id"])
                        continue
                    answer = ctl.action(uid, q.get("data", ""))
                    tg.answer_callback(q["id"])
                    if answer:
                        tg.send_message(int(q["message"]["chat"]["id"]), answer, MAIN_KB)
                    continue

                msg = update.get("message") or {}
                text = msg.get("text")
                sender = msg.get("from") or {}
                chat = msg.get("chat") or {}
                if not text or "id" not in sender or "id" not in chat:
                    continue
                uid = int(sender["id"])
                if uid not in admins:
                    continue
                answer = ctl.text(uid, text)
                if answer:
                    tg.send_message(int(chat["id"]), answer, MAIN_KB)
            failures = 0
        except KeyboardInterrupt:
            break
        except Exception as exc:
            failures += 1
            delay = min(60, 2 ** min(failures, 5))
            print(f"telegram loop error: {exc!r}; retry in {delay}s", flush=True)
            time.sleep(delay)


if __name__ == "__main__":
    main()
