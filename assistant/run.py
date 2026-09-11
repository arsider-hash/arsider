from __future__ import annotations

import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from bot import Controller, MAIN_KB
from core import Store, parse_admins


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


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(item["text"], callback_data=item["callback_data"]) for item in row] for row in MAIN_KB]
    )


def build_controller() -> tuple[Controller, set[int]]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admins = parse_admins(os.getenv("ADMIN_IDS"))
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing. Run pair_admins.py after setting the token.")
    if len(admins) != 2:
        raise SystemExit("Exactly two ADMIN_IDS are required. Run: python pair_admins.py")
    store = Store(os.getenv("DB_PATH", "data/assistant.db"))
    return Controller(store, admins), admins


async def main_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctl: Controller = context.application.bot_data["controller"]
    admins: set[int] = context.application.bot_data["admins"]
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.text or user.id not in admins:
        return
    answer = ctl.text(user.id, message.text)
    if answer:
        await message.reply_text(answer, reply_markup=keyboard())


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ctl: Controller = context.application.bot_data["controller"]
    admins: set[int] = context.application.bot_data["admins"]
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    await query.answer()
    if user.id not in admins:
        return
    answer = ctl.action(user.id, query.data or "")
    if answer and query.message:
        await query.message.reply_text(answer, reply_markup=keyboard())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.getLogger("arsider").exception("telegram handler failure", exc_info=context.error)


def main() -> None:
    load_env()
    ctl, admins = build_controller()
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = Application.builder().token(token).build()
    app.bot_data["controller"] = ctl
    app.bot_data["admins"] = admins
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT, main_message))
    app.add_error_handler(on_error)

    # Long polling means no inbound port, no public server and no tunnel.
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        close_loop=False,
    )


if __name__ == "__main__":
    main()
