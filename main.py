# main.py
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


def main():
    init_db()
    init_models_db()

    register_start_handlers(bot)
    register_callback_handlers(bot)
    register_admin_handlers(bot)
    register_girls_handlers(bot)

    print("✅ Бот успешно запущен!")
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
