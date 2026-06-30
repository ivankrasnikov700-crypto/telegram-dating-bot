# main.py
# Точка входа — инициализация БД, запуск планировщика, запуск бота

import logging
import os
import threading
import time

from config import BOT_TOKEN, LTC_ADDRESS, ADMIN_IDS, DATABASE_URL, MINI_APP_URL
from bot_instance import bot
from database import init_db
from database.models import init_models_db
from database.reviews import init_reviews_db
from database.settings import init_settings_db
from database.schedule import init_schedule_db
from database.withdrawals import init_withdrawals_db
from database.paid_media import init_paid_media_db
from database.chat_sessions import init_chat_sessions_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _check_env():
    """Проверяет обязательные переменные окружения перед стартом."""
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN — токен бота от @BotFather")
    if not DATABASE_URL:
        errors.append("DATABASE_URL — строка подключения PostgreSQL")
    if not LTC_ADDRESS:
        errors.append("LTC_ADDRESS — адрес LTC кошелька")
    if not ADMIN_IDS:
        errors.append("ADMIN_IDS — ID администраторов (через запятую)")
    if errors:
        print("=" * 50)
        print("❌ ОШИБКА: не заданы переменные окружения!")
        print("Добавь в Railway → Variables:")
        for e in errors:
            print("  • " + e)
        print("=" * 50)
        raise SystemExit(1)


_check_env()

from handlers.start import register_start_handlers
from handlers.callback import register_callback_handlers, restore_pending_payments
from handlers.admin import register_admin_handlers
from handlers.girls import register_girls_handlers
from handlers.reviews import register_reviews_handlers
from handlers.vip import register_vip_handlers
from handlers.fan_relay import register_fan_relay_handlers
from handlers.model_dashboard import register_model_dashboard_handlers
from handlers.model_relay import register_model_relay_handlers
from handlers.paid_media import register_paid_media_handlers
from utils.scheduler import start_scheduler, add_scheduler_columns


def main():
    init_db()
    init_models_db()
    init_reviews_db()
    init_settings_db()
    init_schedule_db()
    init_withdrawals_db()
    init_paid_media_db()
    init_chat_sessions_db()
    add_scheduler_columns()

    register_start_handlers(bot)
    register_callback_handlers(bot)
    register_admin_handlers(bot)
    register_girls_handlers(bot)
    register_reviews_handlers(bot)
    register_vip_handlers(bot)
    register_fan_relay_handlers(bot)       # fan → model relay (before model relay)
    register_paid_media_handlers(bot)      # fan unlock paid photos/videos
    register_model_dashboard_handlers(bot) # model /balance /earnings /withdraw (before relay)
    register_model_relay_handlers(bot)     # must be last — catches all model text

    start_scheduler(bot)
    restore_pending_payments(bot)

    import uvicorn
    from api.server import app as fastapi_app
    port = int(os.environ.get("PORT", 8080))

    print("✅ Бот Miss Moldova запущен!")
    print("💳 LTC: " + str(LTC_ADDRESS))
    print("👑 Admins: " + str(ADMIN_IDS))
    logger.info("Bot started")

    if MINI_APP_URL:
        # Webhook mode — FastAPI handles Telegram updates via POST /webhook
        # Set webhook after uvicorn is ready (background thread with delay)
        def _setup_webhook():
            time.sleep(4)  # Wait for uvicorn to bind
            webhook_url = MINI_APP_URL.rstrip("/") + "/webhook"
            try:
                bot.remove_webhook()
                time.sleep(1)
                bot.set_webhook(url=webhook_url)
                print("[BOT] Webhook set: " + webhook_url)
            except Exception as e:
                print("[BOT] Webhook setup failed: " + str(e))

        threading.Thread(target=_setup_webhook, daemon=True).start()
        print("[API] Starting on port " + str(port) + " (webhook mode — no polling)")
        # uvicorn runs in main thread — keeps process alive
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")
    else:
        # Polling mode — local development fallback (MINI_APP_URL not set)
        def _start_api():
            try:
                print("[API] Mini App server starting on port " + str(port))
                uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")
            except Exception as e:
                print("[API] Failed to start: " + str(e))

        threading.Thread(target=_start_api, daemon=True).start()
        print("[BOT] MINI_APP_URL not set — polling mode (local dev)")

        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                err = str(e)
                if "409" in err:
                    print("[INFO] 409 Conflict — other instance running, waiting 60s...")
                    time.sleep(60)
                else:
                    print("[ERROR] Бот упал: " + err)
                    print("[INFO] Перезапуск через 5 секунд...")
                    time.sleep(5)


if __name__ == "__main__":
    main()
