import logging
import telebot
from config import BOT_TOKEN

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# Импортируем обработчики (пока они пустые, но скоро заполним)
from handlers.start import register_start_handlers
from handlers.callback import register_callback_handlers

def main():
    # Регистрация всех обработчиков
    register_start_handlers(bot)
    register_callback_handlers(bot)
    
    print("✅ Бот успешно запущен!")
    logger.info("Bot started")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
