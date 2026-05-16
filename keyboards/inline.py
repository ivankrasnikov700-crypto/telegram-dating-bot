# keyboards/inline.py
# Все inline-клавиатуры бота

from telebot import types

# Курс обмена: 20 MDL = 1 USDT
LEI_RATE = 20
EXCHANGE_ADMIN = "Viktoria11051"


def get_main_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💎 Подписка",        callback_data="subscription"),
        types.InlineKeyboardButton("👭 Девушки",          callback_data="girls"),
        types.InlineKeyboardButton("⭐ Отзывы",           callback_data="reviews"),
        types.InlineKeyboardButton("👑 VIP Клуб",         callback_data="vip_club"),
        types.InlineKeyboardButton("🎁 Бонус дня",        callback_data="daily_bonus"),
        types.InlineKeyboardButton("👤 Мой профиль",      callback_data="my_profile"),
        types.InlineKeyboardButton("💎 Купить кристаллы", callback_data="buy_crystals"),
        types.InlineKeyboardButton("ℹ️ О системе",        callback_data="about_system")
    )
    return markup


def get_subscription_menu() -> types.InlineKeyboardMarkup:
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
        types.InlineKeyboardButton("« Назад", callback_data="back_to_menu")
    )
    return markup


def get_crystal_packs_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "🧪 1 кристалл — $0.1 (тест)",
            callback_data="crystal_pack_test"
        ),
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
        types.InlineKeyboardButton("« Назад", callback_data="back_to_menu")
    )
    return markup


def get_payment_method_keyboard(plan_key: str, back_callback: str) -> types.InlineKeyboardMarkup:
    """Выбор способа оплаты: LTC-крипта или обмен через карту."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "🔷 Оплатить криптой (LTC)",
            callback_data="ltc_" + plan_key
        ),
        types.InlineKeyboardButton(
            "💳 Обмен — Mastercard / Visa",
            callback_data="exch_" + plan_key
        ),
        types.InlineKeyboardButton("« Назад", callback_data=back_callback)
    )
    return markup


def get_exchange_card_keyboard(plan_key: str) -> types.InlineKeyboardMarkup:
    """Выбор типа карты для обмена."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💳 Mastercard", callback_data="mc_" + plan_key),
        types.InlineKeyboardButton("💳 Visa",       callback_data="vi_" + plan_key)
    )
    markup.add(
        types.InlineKeyboardButton("« Назад", callback_data=plan_key)
    )
    return markup


def get_exchange_contact_keyboard() -> types.InlineKeyboardMarkup:
    """Кнопка связи с администратором обмена + главное меню."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(
            "💬 Написать @" + EXCHANGE_ADMIN,
            url="https://t.me/" + EXCHANGE_ADMIN
        ),
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")
    )
    return markup


def get_payment_keyboard(amount_ltc: float, wallet: str) -> types.InlineKeyboardMarkup:
    """Клавиатура оплаты LTC."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Копировать адрес",  callback_data="copy_wallet"),
        types.InlineKeyboardButton("💰 Копировать сумму",  callback_data="copy_amount_" + str(amount_ltc))
    )
    markup.add(
        types.InlineKeyboardButton(
            "🔗 Открыть в блокчейне",
            url="https://live.blockcypher.com/ltc/address/" + wallet
        )
    )
    markup.add(
        types.InlineKeyboardButton("✅ Я оплатил", callback_data="payment_confirmed"),
        types.InlineKeyboardButton("❌ Отмена",    callback_data="back_to_menu")
    )
    return markup


def get_profile_menu(has_premium: bool = False) -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not has_premium:
        markup.add(
            types.InlineKeyboardButton("💎 Оформить подписку", callback_data="subscription")
        )
    markup.add(
        types.InlineKeyboardButton("💎 Купить кристаллы",    callback_data="buy_crystals"),
        types.InlineKeyboardButton("📊 История транзакций",  callback_data="crystal_history"),
        types.InlineKeyboardButton("« Назад",                callback_data="back_to_menu")
    )
    return markup


def get_confirmation_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Я оплатил", callback_data="payment_confirmed"),
        types.InlineKeyboardButton("❌ Отмена",    callback_data="back_to_menu")
    )
    return markup
