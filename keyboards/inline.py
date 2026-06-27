# keyboards/inline.py
# Все inline-клавиатуры бота

from telebot import types
from config import MINI_APP_URL

EXCHANGE_ADMIN = "Viktoria11051"
LEI_RATE = 20


def get_main_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    if MINI_APP_URL:
        girls_btn = types.InlineKeyboardButton(
            "👭 Девушки", web_app=types.WebAppInfo(url=MINI_APP_URL)
        )
    else:
        girls_btn = types.InlineKeyboardButton("👭 Девушки", callback_data="girls")
    markup.add(
        types.InlineKeyboardButton("💵 Пополнить баланс", callback_data="topup_balance"),
        girls_btn,
        types.InlineKeyboardButton("⭐ Отзывы",           callback_data="reviews"),
        types.InlineKeyboardButton("👑 VIP Клуб",         callback_data="vip_club"),
        types.InlineKeyboardButton("👤 Мой профиль",      callback_data="my_profile"),
        types.InlineKeyboardButton("ℹ️ О системе",        callback_data="about_system")
    )
    return markup


def get_topup_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💵 $10",  callback_data="topup_10"),
        types.InlineKeyboardButton("💵 $25",  callback_data="topup_25"),
        types.InlineKeyboardButton("💵 $50",  callback_data="topup_50"),
        types.InlineKeyboardButton("« Назад", callback_data="back_to_menu")
    )
    return markup


def get_profile_menu() -> types.InlineKeyboardMarkup:
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💵 Пополнить баланс",  callback_data="topup_balance"),
        types.InlineKeyboardButton("📊 История транзакций", callback_data="tx_history"),
        types.InlineKeyboardButton("« Назад",               callback_data="back_to_menu")
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
