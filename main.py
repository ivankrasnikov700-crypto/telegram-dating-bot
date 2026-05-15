# main.py
# Точка входа — инициализация БД, запуск планировщика, запуск бота

import logging
import telebot
import time
from config import BOT_TOKEN, LTC_ADDRESS, ADMIN_IDS, DATABASE_URL
from database import init_db
from database.models import init_models_db

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
        errors.append("DATABASE_URL — строка подключения PostgreSQL (добавь PostgreSQL сервис в Railway)")
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
from handlers.callback import register_callback_handlers
from handlers.admin import register_admin_handlers
from handlers.girls import register_girls_handlers
from utils.scheduler import start_scheduler, add_scheduler_columns


def main():
    init_db()
    init_models_db()
    add_scheduler_columns()

    register_start_handlers(bot)
    register_callback_handlers(bot)
    register_admin_handlers(bot)
    register_girls_handlers(bot)

    start_scheduler(bot)

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
