# utils/payments.py
# Генерация платёжных счетов
# Изменено:
# 1. Уникальный хвост в сумме LTC — каждый счёт уникален
#    Два пользователя получат разные суммы → независимое подтверждение
# 2. Добавлен тестовый тариф test_2min ($1, Premium, 2 минуты)
#    УДАЛИТЬ перед боевым запуском

import time
import uuid
import random
import requests
from config import LTC_ADDRESS

# ─────────────────────────────────────────────
# Тарифы подписок
# ─────────────────────────────────────────────

SUBSCRIPTION_PRICES: dict = {

    "fan_30": {
        "name":        "🌸 Fan",
        "usd":         25,
        "days":        30,
        "minutes":     0,
        "crystals":    250,
        "description": "Превью профилей (3 фото)",
        "perks": [
            "📸 3 фото каждой модели",
            "💎 250 кристаллов",
            "👁 Просмотр каталога",
            "💬 Чат с моделями (10 💎)",
        ]
    },
    "premium_90": {
        "name":        "👑 Premium",
        "usd":         50,
        "days":        90,
        "minutes":     0,
        "crystals":    600,
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

# ─────────────────────────────────────────────
# Пакеты кристаллов
# ─────────────────────────────────────────────

CRYSTAL_PACKS: dict = {
    "pack_50": {
        "name":     "Стартовый",
        "usd":      5,
        "crystals": 50,
        "bonus":    0
    },
    "pack_120": {
        "name":     "Популярный",
        "usd":      10,
        "crystals": 100,
        "bonus":    20
    },
    "pack_300": {
        "name":     "Выгодный",
        "usd":      25,
        "crystals": 250,
        "bonus":    50
    },
    "pack_650": {
        "name":     "Максимальный",
        "usd":      50,
        "crystals": 500,
        "bonus":    150
    }
}


# ─────────────────────────────────────────────
# Курс LTC
# ─────────────────────────────────────────────

def get_ltc_rate() -> float:
    """
    Получает актуальный курс LTC/USD с CoinGecko.
    Если API недоступен — резервный курс 80.0
    """
    FALLBACK_RATE = 80.0
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {"ids": "litecoin", "vs_currencies": "usd"}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        rate = float(response.json()["litecoin"]["usd"])
        print("[RATE] Курс LTC/USD: $" + str(rate))
        return rate
    except requests.exceptions.Timeout:
        print("[RATE] Timeout, резервный курс $" + str(FALLBACK_RATE))
        return FALLBACK_RATE
    except requests.exceptions.ConnectionError:
        print("[RATE] Нет соединения, резервный курс $" + str(FALLBACK_RATE))
        return FALLBACK_RATE
    except Exception as e:
        print("[RATE] Ошибка: " + str(e) + ", резервный курс $" + str(FALLBACK_RATE))
        return FALLBACK_RATE


# ─────────────────────────────────────────────
# Генерация счетов
# ─────────────────────────────────────────────

def _unique_amount(base_ltc: float) -> float:
    """
    Добавляет уникальный хвост к сумме LTC.
    Каждый счёт получает свою уникальную сумму —
    два пользователя с одной подпиской не перепутаются.

    Пример: 0.312450 → 0.312453 (хвост +0.000003)
    Разница ~$0.0002 — незаметна для покупателя.
    """
    tail = random.randint(1, 9) / 1_000_000  # от 0.000001 до 0.000009
    return round(base_ltc + tail, 6)


def generate_payment_invoice(sub_type: str, user_id: int) -> dict:
    """
    Генерирует уникальный счёт на оплату подписки.
    Каждый вызов создаёт счёт с уникальной суммой LTC.
    """
    sub_info = SUBSCRIPTION_PRICES.get(sub_type, SUBSCRIPTION_PRICES["fan_30"])

    ltc_rate = get_ltc_rate()
    base_amount = round(sub_info["usd"] / ltc_rate, 6)
    amount_ltc = _unique_amount(base_amount)  # уникальная сумма

    payment_id = str(uuid.uuid4())[:8].upper()

    return {
        "payment_id":      payment_id,
        "user_id":         user_id,
        "sub_type":        sub_type,
        "sub_name":        sub_info["name"],
        "sub_description": sub_info["description"],
        "perks":           sub_info["perks"],
        "amount_usd":      sub_info["usd"],
        "amount_ltc":      amount_ltc,
        "ltc_rate":        ltc_rate,
        "crystals":        sub_info["crystals"],
        "days":            sub_info["days"],
        "minutes":         sub_info.get("minutes", 0),  # для тестовой подписки
        "wallet":          LTC_ADDRESS,
        "created_at":      int(time.time()),
        "expires_at":      int(time.time()) + 3600,
        "type":            "subscription"
    }


def generate_crystal_invoice(pack_type: str, user_id: int) -> dict:
    """Генерирует уникальный счёт на покупку кристаллов."""
    pack_info = CRYSTAL_PACKS.get(pack_type, CRYSTAL_PACKS["pack_50"])

    ltc_rate = get_ltc_rate()
    base_amount = round(pack_info["usd"] / ltc_rate, 6)
    amount_ltc = _unique_amount(base_amount)  # уникальная сумма

    payment_id = str(uuid.uuid4())[:8].upper()
    total_crystals = pack_info["crystals"] + pack_info["bonus"]

    return {
        "payment_id":     payment_id,
        "user_id":        user_id,
        "pack_type":      pack_type,
        "pack_name":      pack_info["name"],
        "amount_usd":     pack_info["usd"],
        "amount_ltc":     amount_ltc,
        "ltc_rate":       ltc_rate,
        "crystals":       pack_info["crystals"],
        "bonus":          pack_info["bonus"],
        "total_crystals": total_crystals,
        "wallet":         LTC_ADDRESS,
        "created_at":     int(time.time()),
        "expires_at":     int(time.time()) + 3600,
        "type":           "crystals"
    }


# ─────────────────────────────────────────────
# Форматирование сообщения счёта
# ─────────────────────────────────────────────

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

    # Для тестовой подписки показываем минуты вместо дней
    minutes = invoice.get("minutes", 0)
    if minutes > 0:
        duration_text = "⏱ Срок: *" + str(minutes) + " минуты* (тест)\n"
    else:
        duration_text = "📅 Срок: *" + str(invoice["days"]) + " дней*\n"

    return (
        "💳 *" + invoice["sub_name"] + " — подписка*\n"
        "_" + invoice["sub_description"] + "_\n\n"
        "🎁 *Что входит:*\n" + perks_text + "\n\n"
        "🆔 ID платежа: `" + invoice["payment_id"] + "`\n\n"
        + duration_text +
        "💰 Сумма: `" + str(invoice["amount_ltc"]) + " LTC`\n"
        "💵 (~$" + str(invoice["amount_usd"]) + " USD)\n"
        "📈 Курс: $`" + str(invoice["ltc_rate"]) + "`\n\n"
        "📬 Адрес кошелька:\n"
        "`" + invoice["wallet"] + "`\n\n"
        "⏰ Счёт действителен 60 минут\n\n"
        "После оплаты нажми ✅ *Я оплатил*"
    )
