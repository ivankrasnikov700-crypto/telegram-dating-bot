from telebot import types

def get_main_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("👋 Приветствие", callback_data="hello"))
    markup.add(types.InlineKeyboardButton("⭐ Премиум / Подписка", callback_data="subscription"))
    markup.add(types.InlineKeyboardButton("👭 Девушки", callback_data="girls"))
    return markup

def get_subscription_menu():
    """Меню выбора подписки"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🆓 Обычная подписка (бесплатно)", callback_data="sub_free"))
    markup.add(types.InlineKeyboardButton("⭐ Премиум 1 месяц ($50)", callback_data="sub_premium_1month"))
    markup.add(types.InlineKeyboardButton("⭐⭐ Премиум 3 месяца ($100)", callback_data="sub_premium_3months"))
    markup.add(types.InlineKeyboardButton("« Назад", callback_data="back_to_menu"))
    return markup

def get_payment_keyboard(amount_ltc, wallet):
    """Клавиатура для оплаты с кнопками"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Кнопки копирования адреса и суммы
    markup.add(
        types.InlineKeyboardButton("📋 Копировать адрес", callback_data="copy_wallet"),
        types.InlineKeyboardButton("💰 Копировать сумму", callback_data=f"copy_amount_{amount_ltc}")
    )
    
    # Кнопка ссылки на кошелёк в блокчейне
    markup.add(
        types.InlineKeyboardButton("🔗 Открыть в блокчейне", 
                                   url=f"https://blockchair.com/litecoin/address/{wallet}")
    )
    
    # Кнопки подтверждения
    markup.add(
        types.InlineKeyboardButton("✅ Я оплатил", callback_data="payment_confirmed"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="subscription")
    )
    
    return markup

def get_confirmation_menu():
    """Меню после выбора премиума"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("✅ Я оплатил", callback_data="payment_confirmed"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="subscription"))
    return markup
