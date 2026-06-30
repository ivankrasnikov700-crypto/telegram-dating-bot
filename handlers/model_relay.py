import io
import re
import time
import requests
from database import get_user, get_connection, increment_warning
from database.chat_sessions import (
    get_model_active_chats,
    deactivate_chat,
    deactivate_all_model_chats,
)
from database.models import get_model
from database.paid_media import create_paid_media
from utils.notify import notify_channel
from config import BOT_TOKEN

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

def process_model_reply(bot, model_id: int, fan_id: int,
                        text_content: str, message_id: int = None) -> dict:
    """
    Validates and relays a model's text message to a fan.

    Fraud → 3-strike system:
        Strike 1 & 2: delete message, warn model [N/2], log to admin channel
        Strike 3+:    ban model, deactivate ALL chats, alert admin channel

    Clean → forward message to fan anonymously.

    Returns:
        {"ok": True}
        {"ok": False, "warning": N, "reason": str}
        {"ok": False, "banned": True, "reason": str}
    """
    is_fraud, trigger = check_for_fraud(text_content)

    if is_fraud:
        new_count = increment_warning(model_id)

        # Always try to delete the offending message
        if message_id:
            try:
                bot.delete_message(model_id, message_id)
            except Exception:
                pass

        if new_count <= 2:
            # Warning — no ban yet
            try:
                bot.send_message(
                    model_id,
                    "⚠️ Предупреждение [" + str(new_count) + "/2]\n\n"
                    "Триггер: " + trigger + "\n"
                    "Сообщение заблокировано и удалено.\n\n"
                    "На 3-м нарушении аккаунт будет заблокирован немедленно."
                )
            except Exception as e:
                print("[RELAY] Не удалось отправить предупреждение модели " + str(model_id) + ": " + str(e))

            alert = (
                "⚠️ АНТИФРОД — ПРЕДУПРЕЖДЕНИЕ [" + str(new_count) + "/2]\n"
                "━━━━━━━━━━━━━━━\n"
                "👩 Модель ID: " + str(model_id) + "\n"
                "👤 Фанат ID: " + str(fan_id) + "\n"
                "⚡ Триггер: " + trigger + "\n"
                "📝 Сообщение:\n«" + text_content[:300] + "»"
            )
            notify_channel(bot, alert)
            print("[RELAY] WARNING " + str(new_count) + "/2 model " + str(model_id) + " trigger=" + trigger)
            return {"ok": False, "warning": new_count, "reason": trigger}

        # Strike 3+ → permanent ban
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_banned = 1 WHERE user_id = %s",
            (model_id,)
        )
        conn.commit()
        conn.close()

        closed = deactivate_all_model_chats(model_id)

        alert = (
            "🚨 АНТИФРОД — АВТОБАН (3-е нарушение)\n"
            "━━━━━━━━━━━━━━━\n"
            "👩 Модель ID: " + str(model_id) + "\n"
            "👤 Фанат ID: " + str(fan_id) + "\n"
            "⚡ Триггер: " + trigger + "\n"
            "🔒 Закрыто чатов: " + str(closed) + "\n"
            "📝 Сообщение:\n«" + text_content[:300] + "»"
        )
        notify_channel(bot, alert)

        try:
            bot.send_message(
                model_id,
                "❌ Ваш аккаунт заблокирован.\n\n"
                "Причина: 3 нарушения — попытка передать контактные данные вне платформы.\n"
                "Это нарушает правила Miss Moldova.\n\n"
                "По вопросам обращайтесь к администратору."
            )
        except Exception as e:
            print("[RELAY] Не удалось уведомить модель " + str(model_id) + ": " + str(e))

        print("[RELAY] AUTOBAN model " + str(model_id) + " (strike 3) trigger=" + trigger)
        return {"ok": False, "banned": True, "reason": trigger}

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

# model_id → {"file_id": str, "file_type": str, "timestamp": int}
_pending_media = {}
# set of model_ids currently waiting for price input
_awaiting_price: set = set()


def _build_fan_selector(bot, model_id: int, text: str, chats: list, message_id: int = None):
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
        "text":       text,
        "message_id": message_id,
        "timestamp":  int(time.time()),
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
    1. Photo/video handler — model sends paid media, prompts for price
    2. Text handler — either price input (FSM) or anti-fraud text relay
    3. Callback handler — fan selector when model has multiple active chats
    """

    @bot.message_handler(
        content_types=['photo', 'video'],
        func=lambda msg: _is_model_message(msg)
    )
    def model_media_handler(message):
        model_id = message.from_user.id

        chats = get_model_active_chats(model_id)
        if not chats:
            bot.send_message(
                model_id,
                "📭 У тебя нет активных чатов — некому отправить медиа."
            )
            return

        if message.content_type == 'photo':
            file_id   = message.photo[-1].file_id
            file_type = 'photo'
        else:
            file_id   = message.video.file_id
            file_type = 'video'

        _pending_media[model_id] = {
            "file_id":   file_id,
            "file_type": file_type,
            "timestamp": int(time.time()),
        }
        _awaiting_price.add(model_id)

        type_label = "фото" if file_type == "photo" else "видео"
        bot.send_message(
            model_id,
            "🔒 Платное " + type_label + "\n\n"
            "Укажи цену в USD (например: 5):\n"
            "Минимум $1, фанат увидит размытое превью + замок 🔒\n\n"
            "Введи 0 — отправить бесплатно как обычное сообщение."
        )

    @bot.message_handler(
        content_types=['text'],
        func=lambda msg: _is_model_message(msg)
    )
    def model_text_relay(message):
        model_id = message.from_user.id
        text     = message.text or ""

        if text.startswith('/'):
            return  # Let command handlers take over

        # Price FSM: model is setting a price for pending media
        if model_id in _awaiting_price:
            _awaiting_price.discard(model_id)
            pending = _pending_media.pop(model_id, None)

            if not pending or int(time.time()) - pending["timestamp"] > 300:
                bot.send_message(model_id, "⏰ Время вышло. Отправь медиа заново.")
                return

            price_str = text.strip().replace(",", ".").replace("$", "")
            try:
                price = float(price_str)
            except ValueError:
                bot.send_message(model_id, "❌ Введи число, например: 5")
                _pending_media[model_id] = pending
                _awaiting_price.add(model_id)
                return

            if price < 0:
                price = 0

            chats = get_model_active_chats(model_id)
            if not chats:
                bot.send_message(model_id, "📭 Нет активных чатов — некому отправить.")
                return

            if price == 0:
                # Free — send directly
                _send_free_media(bot, model_id, pending, chats)
            else:
                _send_paid_media(bot, model_id, pending, chats, price)
            return

        # Normal text relay
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
            process_model_reply(bot, model_id, fan_id, text, message_id=message.message_id)
        else:
            _build_fan_selector(bot, model_id, text, chats, message_id=message.message_id)

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

        result = process_model_reply(bot, model_id, fan_id, pending["text"],
                                     message_id=pending.get("message_id"))

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


def _blur_photo(file_id: str) -> bytes | None:
    """Download a Telegram photo, apply Gaussian blur, return JPEG bytes."""
    try:
        from PIL import Image, ImageFilter
        import telebot
        # We need to download via Telegram API
        url = "https://api.telegram.org/bot" + BOT_TOKEN + "/getFile?file_id=" + file_id
        resp = requests.get(url, timeout=15)
        data = resp.json()
        file_path = data["result"]["file_path"]
        dl_url    = "https://api.telegram.org/file/bot" + BOT_TOKEN + "/" + file_path
        img_resp  = requests.get(dl_url, timeout=30)
        img       = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
        blurred   = img.filter(ImageFilter.GaussianBlur(radius=20))
        buf       = io.BytesIO()
        blurred.save(buf, format="JPEG", quality=70)
        buf.seek(0)
        return buf
    except Exception as e:
        print("[PAID MEDIA] Blur error: " + str(e))
        return None


def _send_free_media(bot, model_id: int, pending: dict, chats: list):
    """Relay free photo/video to all active fans."""
    model_name = get_model_display_name(model_id)
    file_id    = pending["file_id"]
    file_type  = pending["file_type"]

    for chat in chats:
        fan_id = chat["fan_id"]
        try:
            if file_type == "video":
                bot.send_video(fan_id, file_id, caption="🎬 " + model_name)
            else:
                bot.send_photo(fan_id, file_id, caption="📸 " + model_name)
        except Exception as e:
            print("[RELAY] Не удалось доставить медиа фанату " + str(fan_id) + ": " + str(e))

    bot.send_message(model_id, "✅ Медиа отправлено фанатам (" + str(len(chats)) + " чел.)")


def _send_paid_media(bot, model_id: int, pending: dict, chats: list, price: float):
    """Create blurred preview, send to all active fans as paid media."""
    from telebot import types

    file_id   = pending["file_id"]
    file_type = pending["file_type"]
    price_str = "$" + str(round(price, 2))

    # Prepare blurred bytes once (photos only)
    blurred_file_id = None
    blurred_buf     = _blur_photo(file_id) if file_type == "photo" else None

    sent_count = 0
    media_ids  = []

    for chat in chats:
        fan_id   = chat["fan_id"]
        media_id = create_paid_media(model_id, fan_id, file_id, file_type, price, blurred_file_id)
        media_ids.append(media_id)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "🔓 Разблокировать за " + price_str,
            callback_data="unlock_" + str(media_id)
        ))

        try:
            if file_type == "video":
                bot.send_message(
                    fan_id,
                    "🎬 Эксклюзивное видео — закрыто 🔒\n"
                    "Цена разблокировки: " + price_str,
                    reply_markup=markup
                )
            elif blurred_file_id is not None:
                # Use cached Telegram file_id from the first upload
                bot.send_photo(
                    fan_id,
                    blurred_file_id,
                    caption="🔒 Закрытое фото — " + price_str,
                    reply_markup=markup
                )
            elif blurred_buf is not None:
                # First upload — send bytes, cache resulting file_id
                blurred_buf.seek(0)
                sent = bot.send_photo(
                    fan_id,
                    blurred_buf,
                    caption="🔒 Закрытое фото — " + price_str,
                    reply_markup=markup
                )
                blurred_file_id = sent.photo[-1].file_id
            else:
                # Pillow unavailable — text fallback
                bot.send_message(
                    fan_id,
                    "📸 Закрытое фото — " + price_str + " 🔒",
                    reply_markup=markup
                )
            sent_count += 1
        except Exception as e:
            print("[PAID MEDIA] Ошибка отправки фанату " + str(fan_id) + ": " + str(e))

    # Backfill preview_file_id for all records now that we have it
    if blurred_file_id:
        for mid in media_ids:
            _update_preview_file_id(mid, blurred_file_id)

    type_label = "фото" if file_type == "photo" else "видео"
    bot.send_message(
        model_id,
        "✅ Платное " + type_label + " отправлено!\n"
        "💰 Цена: " + price_str + "\n"
        "👥 Фанатов получили: " + str(sent_count) + "\n\n"
        "Когда фанат разблокирует — получишь $" + str(round(price * 0.70, 2)) + " 💵"
    )


def _update_preview_file_id(media_id: int, preview_file_id: str):
    try:
        from database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE paid_media SET preview_file_id = %s WHERE id = %s",
            (preview_file_id, media_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print("[PAID MEDIA] preview_file_id update error: " + str(e))
