# keyboards/inline.py
# Все inline-клавиатуры бота
# Добавлено: тестовая кнопка sub_test_2min — удалить перед продакшном

from telebot import types


def get_main_menu() -> types.InlineKeyboardMarkup:
    """Главное меню"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💎 Подписка", callback_data="subscription"),
        types.InlineKeyboardButton("👭 Девушки", callback_data="girls"),
        types.InlineKeyboardButton("👤 Мой профиль", callback_data="my_profile"),
        types.InlineKeyboardButton("💎 Купить кристаллы", callback_data="buy_crystals"),
        types.InlineKeyboardButton("ℹ️ О системе", callback_data="about_system")
    )
    return markup


def get_subscription_menu() -> types.InlineKeyboardMarkup:
    """Меню выбора подписки"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "🌸 Fan — 30 дней ($25) • 250 💎",
            callback_data="sub_fan_30"
        ),
        types.InlineKeyboardButton(
            "👑 Premium — 90 дней ($50) • 600 💎",
            callback_data="sub_premium_90"
        ),
        types.InlineKeyboardButton(
            "« Назад",
            callback_data="back_to_menu"
        )
    )
    return markup


def get_crystal_packs_menu() -> types.InlineKeyboardMarkup:
    """Меню покупки кристаллов"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "💎 50 кристаллов — $5",
            callback_data="crystal_pack_50"
        ),
        types.InlineKeyboardButton(
            "💎 120 кристаллов — $10 (+20 бонус)",
            callback_data="crystal_pack_120"
        ),
        types.InlineKeyboardButton(
            "💎 300 кристаллов — $25 (+50 бонус)",
            callback_data="crystal_pack_300"
        ),
        types.InlineKeyboardButton(
            "💎 650 кристаллов — $50 (+150 бонус)",
            callback_data="crystal_pack_650"
        ),
        types.InlineKeyboardButton(
            "« Назад",
            callback_data="back_to_menu"
        )
    )
    return markup


def get_payment_keyboard(amount_ltc: float, wallet: str) -> types.InlineKeyboardMarkup:
    """Клавиатура для оплаты"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "📋 Копировать адрес",
            callback_data="copy_wallet"
        ),
        types.InlineKeyboardButton(
            "💰 Копировать сумму",
            callback_data="copy_amount_" + str(amount_ltc)
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔗 Открыть в блокчейне",
            url="https://live.blockcypher.com/ltc/address/" + wallet
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "✅ Я оплатил",
            callback_data="payment_confirmed"
        ),
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="back_to_menu"
        )
    )
    return markup


def get_profile_menu(has_premium: bool = False) -> types.InlineKeyboardMarkup:
    """Меню профиля пользователя"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not has_premium:
        markup.add(
            types.InlineKeyboardButton(
                "💎 Оформить подписку",
                callback_data="subscription"
            )
        )
    markup.add(
        types.InlineKeyboardButton(
            "💎 Купить кристаллы",
            callback_data="buy_crystals"
        ),
        types.InlineKeyboardButton(
            "📊 История транзакций",
            callback_data="crystal_history"
        ),
        types.InlineKeyboardButton(
            "« Назад",
            callback_data="back_to_menu"
        )
    )
    return markup


def get_confirmation_menu() -> types.InlineKeyboardMarkup:
    """Меню подтверждения оплаты"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "✅ Я оплатил",
            callback_data="payment_confirmed"
        ),
        types.InlineKeyboardButton(
            "❌ Отмена",
            callback_data="back_to_menu"
        )
    )
    return markup
