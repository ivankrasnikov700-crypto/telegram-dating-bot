from telebot import types
from keyboards.inline import get_main_menu

def register_start_handlers(bot):
    
    @bot.message_handler(commands=['start'])
    def start(message):
        markup = get_main_menu()
        bot.send_message(
            message.chat.id,
            "❤️ Добро пожаловать в Dating Premium!\n\n"
            "Здесь девушки сами размещают свой контент 🔥",
            reply_markup=markup
        )
