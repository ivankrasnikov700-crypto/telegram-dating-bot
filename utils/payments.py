# utils/payments.py
# Модуль для генерации платёжных счетов
# Курс LTC берётся в реальном времени с CoinGecko API

import time
import uuid
import requests
from config import LTC_ADDRESS

# Тарифы подписок с кристаллами
SUBSCRIPTION_PRICES: dict = {
    "fan_30": {
        "name": "🌸 Fan",
        "usd": 25,
        "days": 30,
        "crystals": 250,
        "description": "Превью профилей (3 фото)",
        "perks": [
            "📸 3 фото каждой модели",
            "💎 250 кристаллов",
            "👁 Просмотр каталога",
            "💬 Чат с моделями (10 💎)",
        ]
    },
    "premium_90": {
        "name": "👑 Premium",
        "usd": 50,
        "days": 90,
        "crystals": 600,
        "description": "Полный доступ ко всему контенту",
        "perks": [
            "📸 Все фото и видео",
            "💎 600 кристаллов",
            "🔓 Эксклюзивный контент",
            "💬 Чат с моделями (10 💎)",
            "🎁 Подарки моделям (20 💎)",
            "⭐ Приоритет в каталоге",
        ]
    }
}

# Пакеты кристаллов для отдельной покупки
CRYSTAL_PACKS: dict = {
    "pack_50": {
        "name": "Стартовый",
        "usd": 5,
        "crystals": 50,
        "bonus": 0
    },
    "pack_120": {
        "name": "Популярный",
        "usd": 10,
        "crystals": 100,
        "bonus": 20
    },
    "pack_300": {
        "name": "Выгодный",
        "usd": 25,
        "crystals": 250,
        "bonus": 50
    },
    "pack_650": {
        "name": "Максимальный",
        "usd": 50,
        "crystals": 500,
        "bonus": 150
    }
}


def get_ltc_rate() -> float:
    """
    Получает актуальный курс LTC/USD с CoinGecko API.

    Returns:
        float: текущий курс LTC в USD
        Если API недоступен — возвращает резервный курс 80.0
    """
    FALLBACK_RATE = 80.0

    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "litecoin",
            "vs_currencies": "usd"
        }
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        rate = float(data["litecoin"]["usd"])
        print("[RATE] Актуальный курс LTC/USD: $" + str(rate))
        return rate

    except requests.exceptions.Timeout:
        print("[RATE WARNING] Timeout, резервный курс $" + str(FALLBACK_RATE))
        return FALLBACK_RATE

    except requests.exceptions.ConnectionError:
        print("[RATE WARNING] Нет соединения, резервный курс $" + str(FALLBACK_RATE))
        return FALLBACK_RATE

    except Exception as e:
        print("[RATE ERROR] " + str(e) + ", резервный курс $" + str(FALLBACK_RATE))
        return FALLBACK_RATE


def generate_payment_invoice(sub_type: str, user_id: int) -> dict:
    """
    Генерирует счёт на оплату подписки.

    Args:
        sub_type: тип подписки (fan_30 / premium_90)
        user_id: telegram id пользователя

    Returns:
        dict со всеми деталями платежа
    """
    sub_info = SUBSCRIPTION_PRICES.get(
        sub_type,
        SUBSCRIPTION_PRICES["fan_30"]
    )

    ltc_rate = get_ltc_rate()
    amount_ltc = round(sub_info["usd"] / ltc_rate, 6)
    payment_id = str(uuid.uuid4())[:8].upper()

    return {
        "payment_id": payment_id,
        "user_id": user_id,
        "sub_type": sub_type,
        "sub_name": sub_info["name"],
        "sub_description": sub_info["description"],
        "perks": sub_info["perks"],
        "amount_usd": sub_info["usd"],
        "amount_ltc": amount_ltc,
        "ltc_rate": ltc_rate,
        "crystals": sub_info["crystals"],
        "wallet": LTC_ADDRESS,
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + 3600,
        "days": sub_info["days"],
        "type": "subscription"
    }


def generate_crystal_invoice(pack_type: str, user_id: int) -> dict:
    """
    Генерирует счёт на покупку кристаллов.

    Args:
        pack_type: тип пакета (pack_50/pack_120/pack_300/pack_650)
        user_id: telegram id пользователя

    Returns:
        dict со всеми деталями платежа
    """
    pack_info = CRYSTAL_PACKS.get(
        pack_type,
        CRYSTAL_PACKS["pack_50"]
    )

    ltc_rate = get_ltc_rate()
    amount_ltc = round(pack_info["usd"] / ltc_rate, 6)
    payment_id = str(uuid.uuid4())[:8].upper()
    total_crystals = pack_info["crystals"] + pack_info["bonus"]

    return {
        "payment_id": payment_id,
        "user_id": user_id,
        "pack_type": pack_type,
        "pack_name": pack_info["name"],
        "amount_usd": pack_info["usd"],
        "amount_ltc": amount_ltc,
        "ltc_rate": ltc_rate,
        "crystals": pack_info["crystals"],
        "bonus": pack_info["bonus"],
        "total_crystals": total_crystals,
        "wallet": LTC_ADDRESS,
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + 3600,
        "type": "crystals"
    }


def format_payment_message(invoice: dict) -> str:
    """Форматирует сообщение с деталями платежа"""

    if invoice.get("type") == "crystals":
        bonus_text = ""
        if invoice["bonus"] > 0:
            bonus_text = "\n🎁 Бонус: +" + str(invoice["bonus"]) + " 💎"

        return (
            "💎 *Покупка кристаллов — " + invoice["pack_name"] + "*\n\n"
            "🆔 ID платежа: `" + invoice["payment_id"] + "`\n\n"
            "💎 Кристаллов: *" + str(invoice["crystals"]) + "*" + bonus_text + "\n"
            "✨ Итого: *" + str(invoice["total_crystals"]) + " 💎*\n\n"
            "💰 Сумма: `" + str(invoice["amount_ltc"]) + " LTC`\n"
            "💵 (~$" + str(invoice["amount_usd"]) + " USD)\n"
            "📈 Курс: $`" + str(invoice["ltc_rate"]) + "`\n\n"
            "📬 Адрес кошелька:\n"
            "`" + invoice["wallet"] + "`\n\n"
            "⏰ Счёт действителен 60 минут\n\n"
            "После оплаты нажми ✅ *Я оплатил*"
        )

    # Подписка
    perks_text = "\n".join(invoice.get("perks", []))

    return (
        "💳 *" + invoice["sub_name"] + " — подписка*\n"
        "_" + invoice["sub_description"] + "_\n\n"
        "🎁 *Что входит:*\n" + perks_text + "\n\n"
        "🆔 ID платежа: `" + invoice["payment_id"] + "`\n\n"
        "💰 Сумма: `" + str(invoice["amount_ltc"]) + " LTC`\n"
        "💵 (~$" + str(invoice["amount_usd"]) + " USD)\n"
        "📈 Курс: $`" + str(invoice["ltc_rate"]) + "`\n\n"
        "📬 Адрес кошелька:\n"
        "`" + invoice["wallet"] + "`\n\n"
        "⏰ Счёт действителен 60 минут\n\n"
        "После оплаты нажми ✅ *Я оплатил*"
    )