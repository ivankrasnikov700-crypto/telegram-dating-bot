# main.py
# Точка входа — инициализация БД, запуск планировщика, запуск бота

import logging
import telebot
import time
from config import BOT_TOKEN, LTC_ADDRESS, ADMIN_IDS, DATABASE_URL
from database import init_db
from database.models import init_models_db
from database.reviews import init_reviews_db
from database.settings import init_settings_db
from database.schedule import init_schedule_db
from database.withdrawals import init_withdrawals_db
from database.paid_media import init_paid_media_db

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

bot = telebot.TeleBot(BOT_TOKEN)

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

    print("✅ Бот Miss Moldova запущен!")
    print("💳 LTC: " + str(LTC_ADDRESS))
    print("👑 Admins: " + str(ADMIN_IDS))
    logger.info("Bot started")

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print("[ERROR] Бот упал: " + str(e))
            print("[INFO] Перезапуск через 5 секунд...")
            time.sleep(5)


if __name__ == "__main__":
    main()
