from telebot import types

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("👋 Приветствие", callback_data="hello"))
    markup.add(types.InlineKeyboardButton("⭐ Премиум / Подписка", callback_data="premium"))
    markup.add(types.InlineKeyboardButton("👭 Девушки", callback_data="girls"))
    return markup
