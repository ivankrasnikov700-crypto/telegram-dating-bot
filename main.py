# main.py
# Точка входа — запуск бота

import logging
import telebot
from config import BOT_TOKEN
from database import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Создаём экземпляр бота
bot = telebot.TeleBot(BOT_TOKEN)

# Импортируем обработчики
from handlers.start import register_start_handlers
from handlers.callback import register_callback_handlers


def main():
    """Основная функция запуска бота"""

    # Инициализируем базу данных
    init_db()

    # Регистрируем обработчики
    register_start_handlers(bot)
    register_callback_handlers(bot)

    print("✅ Бот успешно запущен!")
    logger.info("Bot started")

    # Запускаем бота
    bot.infinity_polling()


if __name__ == "__main__":
    main()