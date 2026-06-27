import re
import time
from database import get_user, get_connection
from database.chat_sessions import (
    get_model_active_chats,
    deactivate_chat,
)
from database.models import get_model
from utils.notify import notify_channel

# ─────────────────────────────────────────────
# Anti-fraud patterns (compiled once at import)
# ─────────────────────────────────────────────

_FRAUD_PATTERNS = [
    # Telegram @usernames (3+ chars)
    (re.compile(r'@[\w]{3,}', re.IGNORECASE),
     "Telegram-юзернейм (@username)"),

    # Any http/https link
    (re.compile(r'https?://', re.IGNORECASE),
     "Ссылка (http/https)"),

    # t.me deep links (with or without http)
    (re.compile(r't\.me/[\w+@]', re.IGNORECASE),
     "Ссылка t.me"),

    # Known external platforms
    (re.compile(
        r'instagram\.com|tiktok\.com|onlyfans\.com|fans\.ly|'
        r'twitter\.com|x\.com|vk\.com|ok\.ru|facebook\.com|'
        r'telegram\.me|snapchat\.com|youtube\.com',
        re.IGNORECASE),
     "Ссылка на внешнюю платформу"),

    # Russian mobile (+7 / 8 + 10 digits)
    (re.compile(
        r'(?<!\d)(\+?[78][\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{2}[\s\-.]?\d{2})(?!\d)',
        re.IGNORECASE),
     "Номер телефона (RU)"),

    # Moldovan mobile (+373 + 8 digits)
    (re.compile(
        r'(?<!\d)(\+?373[\s\-.]?\d{2}[\s\-.]?\d{3}[\s\-.]?\d{3})(?!\d)',
        re.IGNORECASE),
     "Номер телефона (MD)"),

    # Any 10–11 consecutive digits (other phone formats)
    (re.compile(r'(?<!\d)\d{10,11}(?!\d)'),
     "10-11 цифр подряд (возможный номер)"),
]

_STOP_WORDS = [
    "личка", "в лс", "лс ", " лс", "переходи", "перейди",
    "телеграм", "телега", "тг ", " тг",
    "вотсап", "whatsapp", "вацап",
    "инстаграм", "инста", "instagram",
    "напиши мне", "напишите мне", "напиши в",
    "свяжись", "связаться",
    "контакт", "контакты",
    "директ", "дирек", "директ",
    "вконтакте", "вк ", " вк",
    "фейсбук", "facebook",
    "скинь номер", "дай номер",
    "мой номер", "мой телефон",
    "skype", "скайп",
    "viber", "вайбер",
    "discord", "дискорд",
]


# ─────────────────────────────────────────────
# Core fraud detection
# ─────────────────────────────────────────────

def check_for_fraud(text: str) -> tuple:
    """
    Checks message text for contact leak attempts.

    Returns:
        (True, trigger_description) — fraud detected
        (False, "")                  — message is clean
    """
    lower = text.lower()

    for pattern, label in _FRAUD_PATTERNS:
        if pattern.search(text):
            return True, label

    for word in _STOP_WORDS:
        if word in lower:
            return True, "Стоп-слово: «" + word.strip() + "»"

    return False, ""


# ─────────────────────────────────────────────
# Process model → fan message relay
# ─────────────────────────────────────────────

def process_model_reply(bot, model_id: int, fan_id: int, text_content: str) -> dict:
    """
    Validates and relays a model's text message to a fan.

    If fraud detected:
        - Bans the model (users.is_banned = 1)
        - Deactivates the active chat session
        - Alerts admin channel
        - Notifies the model of the ban

    If clean:
        - Forwards message to fan anonymously

    Returns:
        {"ok": True}  or  {"ok": False, "reason": str}
    """
    is_fraud, trigger = check_for_fraud(text_content)
    chat_id = str(fan_id) + "_" + str(model_id)

    if is_fraud:
        # Ban the model
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_banned = 1 WHERE user_id = %s",
            (model_id,)
        )
        conn.commit()
        conn.close()

        # Kill the chat session
        deactivate_chat(chat_id)

        # Alert admin channel
        alert = (
            "🚨 АНТИФРОД — АВТОБАН\n"
            "━━━━━━━━━━━━━━━\n"
            "👩 Модель ID: " + str(model_id) + "\n"
            "👤 Фанат ID: " + str(fan_id) + "\n"
            "⚡ Триггер: " + trigger + "\n"
            "📝 Сообщение:\n«" + text_content[:300] + "»"
        )
        notify_channel(bot, alert)

        # Notify model
        try:
            bot.send_message(
                model_id,
                "❌ Ваш аккаунт заблокирован.\n\n"
                "Причина: попытка передать контактные данные вне платформы.\n"
                "Это нарушает правила Miss Moldova.\n\n"
                "По вопросам обращайтесь к администратору."
            )
        except Exception as e:
            print("[RELAY] Не удалось уведомить модель " + str(model_id) + ": " + str(e))

        print("[RELAY] AUTOBAN model " + str(model_id) + " trigger=" + trigger)
        return {"ok": False, "reason": trigger}

    # Message is clean — relay to fan
    model_info = get_model_display_name(model_id)
    try:
        bot.send_message(
            fan_id,
            "💌 " + model_info + ":\n\n" + text_content
        )
    except Exception as e:
        print("[RELAY] Не удалось доставить сообщение фанату " + str(fan_id) + ": " + str(e))
        return {"ok": False, "reason": "Telegram delivery error: " + str(e)}

    return {"ok": True}


def get_model_display_name(model_id: int) -> str:
    """Returns model's display name from models table, or generic fallback."""
    try:
        model = get_model(model_id)
        if model:
            return model.get("name", "Модель")
    except Exception:
        pass
    return "Модель"


# ─────────────────────────────────────────────
# Pending model replies (multi-fan routing)
# ─────────────────────────────────────────────

# model_id → {"text": str, "timestamp": int}
_pending_model_messages = {}


def _build_fan_selector(bot, model_id: int, text: str, chats: list):
    """When model has multiple active fans, ask them to pick a recipient."""
    from telebot import types

    markup = types.InlineKeyboardMarkup(row_width=1)
    for chat in chats:
        fan_id     = chat["fan_id"]
        expires_at = chat["expires_at"]
        remaining  = max(0, expires_at - int(time.time()))
        hours_left = remaining // 3600
        label      = "Фанат " + str(fan_id) + " (" + str(hours_left) + "ч)"
        markup.add(types.InlineKeyboardButton(
            label,
            callback_data="relay_to_" + str(fan_id)
        ))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="relay_cancel"))

    _pending_model_messages[model_id] = {
        "text":      text,
        "timestamp": int(time.time()),
    }

    bot.send_message(
        model_id,
        "Кому отправить сообщение?",
        reply_markup=markup
    )


# ─────────────────────────────────────────────
# Handler registration
# ─────────────────────────────────────────────

def register_model_relay_handlers(bot):
    """
    Registers:
    1. Message handler — intercepts all text from models, runs anti-fraud relay
    2. Callback handler — fan selector when model has multiple active chats
    """

    @bot.message_handler(
        content_types=['text'],
        func=lambda msg: _is_model_message(msg)
    )
    def model_text_relay(message):
        model_id = message.from_user.id
        text     = message.text or ""

        if text.startswith('/'):
            return  # Let command handlers take over

        chats = get_model_active_chats(model_id)

        if not chats:
            bot.send_message(
                model_id,
                "📭 У тебя нет активных чатов с фанатами.\n\n"
                "Как только фанат купит сессию — сюда придёт уведомление."
            )
            return

        if len(chats) == 1:
            fan_id = chats[0]["fan_id"]
            process_model_reply(bot, model_id, fan_id, text)
        else:
            _build_fan_selector(bot, model_id, text, chats)

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("relay_to_") or call.data == "relay_cancel"
    )
    def handle_relay_fan_selection(call):
        model_id = call.from_user.id
        bot.answer_callback_query(call.id)

        if call.data == "relay_cancel":
            _pending_model_messages.pop(model_id, None)
            bot.edit_message_text(
                "❌ Отправка отменена.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        fan_id  = int(call.data.replace("relay_to_", ""))
        pending = _pending_model_messages.pop(model_id, None)

        if not pending:
            bot.edit_message_text(
                "❌ Сообщение устарело. Напиши снова.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        # Reject if pending entry is older than 5 minutes
        if int(time.time()) - pending["timestamp"] > 300:
            bot.edit_message_text(
                "⏰ Время выбора истекло. Отправь сообщение заново.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        result = process_model_reply(bot, model_id, fan_id, pending["text"])

        if result["ok"]:
            bot.edit_message_text(
                "✅ Сообщение доставлено фанату.",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.edit_message_text(
                "❌ Сообщение заблокировано: " + result["reason"],
                call.message.chat.id,
                call.message.message_id
            )


def _is_model_message(message) -> bool:
    """True if the sender's user_role is 'model' and they are not banned."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            return False
        return user.get("user_role") == "model" and not user.get("is_banned", 0)
    except Exception:
        return False
