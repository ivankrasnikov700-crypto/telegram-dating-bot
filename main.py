# main.py
# Точка входа — инициализация БД, запуск планировщика, запуск бота
# Добавлено: запуск scheduler для уведомлений об истечении подписки

import logging
import telebot
import time
from config import BOT_TOKEN
from database import init_db
from database.models import init_models_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

from handlers.start import register_start_handlers
from handlers.callback import register_callback_handlers
from handlers.admin import register_admin_handlers
from handlers.girls import register_girls_handlers
from utils.scheduler import start_scheduler, add_scheduler_columns


def main():
    # Инициализация и миграции БД
    init_db()
    init_models_db()

    # Миграция: добавляем колонку subscription_notified если нет
    add_scheduler_columns()

    # Регистрация хендлеров
    register_start_handlers(bot)
    register_callback_handlers(bot)
    register_admin_handlers(bot)
    register_girls_handlers(bot)

    # Запуск планировщика уведомлений в фоне
    start_scheduler(bot)

    print("✅ Бот Miss Moldova запущен!")
    logger.info("Bot started")

    # Автоперезапуск при падении
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print("[ERROR] Бот упал: " + str(e))
            print("[INFO] Перезапуск через 5 секунд...")
            time.sleep(5)


if __name__ == "__main__":
    main()
