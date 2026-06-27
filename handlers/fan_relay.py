import time
from database import get_user
from database.chat_sessions import get_fan_active_chats
from database.models import get_model


# fan_id → {"text": str, "timestamp": int}
_pending_fan_messages = {}


def _relay_fan_to_model(bot, fan_id: int, model_id: int, text: str):
    """Forwards a fan's message to the model anonymously."""
    try:
        bot.send_message(model_id, "💌 Фанат:\n\n" + text)
    except Exception as e:
        print("[FAN_RELAY] Не удалось доставить сообщение модели " + str(model_id) + ": " + str(e))
        try:
            bot.send_message(fan_id, "❌ Не удалось доставить сообщение. Попробуй позже.")
        except Exception:
            pass


def _build_model_selector(bot, fan_id: int, text: str, chats: list):
    """When fan has multiple active chats, ask them to pick the model."""
    from telebot import types

    markup = types.InlineKeyboardMarkup(row_width=1)
    for chat in chats:
        model_id   = chat["model_id"]
        expires_at = chat["expires_at"]
        remaining  = max(0, expires_at - int(time.time()))
        hours_left = remaining // 3600
        model      = get_model(model_id)
        model_name = model.get("name", "Модель " + str(model_id)) if model else "Модель"
        label      = model_name + " (" + str(hours_left) + "ч)"
        markup.add(types.InlineKeyboardButton(
            label,
            callback_data="fan_relay_to_" + str(model_id)
        ))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="fan_relay_cancel"))

    _pending_fan_messages[fan_id] = {
        "text":      text,
        "timestamp": int(time.time()),
    }

    bot.send_message(fan_id, "Кому отправить сообщение?", reply_markup=markup)


def _is_fan_with_active_chat(message) -> bool:
    """True if the sender is a non-banned fan with at least one active chat session."""
    try:
        user = get_user(message.from_user.id)
        if not user:
            return False
        if user.get("user_role") != "fan":
            return False
        if user.get("is_banned", 0):
            return False
        chats = get_fan_active_chats(message.from_user.id)
        return len(chats) > 0
    except Exception:
        return False


def register_fan_relay_handlers(bot):
    """
    Registers:
    1. Message handler — intercepts all text from fans with active chats
    2. Callback handler — model selector when fan has multiple active chats
    """

    @bot.message_handler(
        content_types=['text'],
        func=lambda msg: _is_fan_with_active_chat(msg)
    )
    def fan_text_relay(message):
        fan_id = message.from_user.id
        text   = message.text or ""

        if text.startswith('/'):
            return

        chats = get_fan_active_chats(fan_id)

        if not chats:
            return  # session expired between check and handler

        if len(chats) == 1:
            _relay_fan_to_model(bot, fan_id, chats[0]["model_id"], text)
        else:
            _build_model_selector(bot, fan_id, text, chats)

    @bot.callback_query_handler(
        func=lambda call: (
            call.data.startswith("fan_relay_to_") or call.data == "fan_relay_cancel"
        )
    )
    def handle_fan_relay_selection(call):
        fan_id = call.from_user.id
        bot.answer_callback_query(call.id)

        if call.data == "fan_relay_cancel":
            _pending_fan_messages.pop(fan_id, None)
            bot.edit_message_text(
                "❌ Отправка отменена.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        model_id = int(call.data.replace("fan_relay_to_", ""))
        pending  = _pending_fan_messages.pop(fan_id, None)

        if not pending:
            bot.edit_message_text(
                "❌ Сообщение устарело. Напиши снова.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        if int(time.time()) - pending["timestamp"] > 300:
            bot.edit_message_text(
                "⏰ Время выбора истекло. Отправь сообщение заново.",
                call.message.chat.id,
                call.message.message_id
            )
            return

        _relay_fan_to_model(bot, fan_id, model_id, pending["text"])
        bot.edit_message_text(
            "✅ Сообщение отправлено.",
            call.message.chat.id,
            call.message.message_id
        )
