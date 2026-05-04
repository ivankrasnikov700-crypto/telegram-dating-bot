import telebot
from telebot import types

TOKEN = "8674229249:AAE6LCYcMVpDK8Hq2B--utaCEOlosTrpyQU"

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("👋 Приветствие", callback_data="hello"))
    markup.add(types.InlineKeyboardButton("⭐ Премиум / Подписка", callback_data="premium"))
    markup.add(types.InlineKeyboardButton("👭 Девушки", callback_data="girls"))
    
    bot.send_message(message.chat.id, 
        "❤️ Добро пожаловать в Dating Premium!\n\n"
        "Здесь девушки сами размещают свой контент.\n"
        "Выбирай и оформляй подписку 🔥", 
        reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "hello":
        bot.answer_callback_query(call.id, "Привет! 😊")
        bot.send_message(call.message.chat.id, "Рады тебя видеть в нашем закрытом клубе!")

print("✅ Бот запущен...")
bot.infinity_polling()
