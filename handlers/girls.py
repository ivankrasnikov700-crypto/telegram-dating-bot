# handlers/girls.py
# Каталог моделей — просмотр профилей, превью и премиум контент
# Исправлено:
# 1. Кнопка «Назад к каталогу» — удаляем фото-сообщение, показываем каталог
# 2. Пагинация в каталоге (5 моделей на странице)
# 3. Возраст берётся из _enrich_model() → calculate_age() динамически

from telebot import types
import time
from database import register_user, get_usd_balance
from database.models import get_all_models, get_model, get_preview_media, get_all_media
from database.chat_sessions import (
    get_active_chat,
    activate_day_chat,
    InsufficientBalanceError,
    ActiveChatExistsError,
    CHAT_PRICE_USD,
)
from utils.notify import notify_channel

# Количество моделей на одной странице каталога
MODELS_PER_PAGE = 5


# ─────────────────────────────────────────────
# Вспомогательные функции — клавиатуры
# ─────────────────────────────────────────────

def get_girls_list_keyboard(models: list, page: int, total_pages: int) -> types.InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком моделей + навигация по страницам.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)

    # Кнопки моделей текущей страницы
    for model in models:
        age = model.get("age", "?")
        label = "👩 " + model["name"] + " | " + str(age) + " лет"
        markup.add(
            types.InlineKeyboardButton(
                label,
                callback_data="girl_" + str(model["id"])
            )
        )

    # Навигация по страницам (только если больше одной страницы)
    if total_pages > 1:
        nav_row = []

        if page > 0:
            nav_row.append(
                types.InlineKeyboardButton(
                    "◀️ Назад",
                    callback_data="girls_page_" + str(page - 1)
                )
            )

        # Счётчик страниц — нажатие не делает ничего
        nav_row.append(
            types.InlineKeyboardButton(
                str(page + 1) + "/" + str(total_pages),
                callback_data="noop"
            )
        )

        if page < total_pages - 1:
            nav_row.append(
                types.InlineKeyboardButton(
                    "Вперёд ▶️",
                    callback_data="girls_page_" + str(page + 1)
                )
            )

        markup.row(*nav_row)

    markup.add(
        types.InlineKeyboardButton("« Главное меню", callback_data="back_to_menu")
    )
    return markup


def get_girl_profile_keyboard(model_id: int, has_active_chat: bool,
                              chat_hours_left: int = 0) -> types.InlineKeyboardMarkup:
    """Клавиатура профиля модели."""
    markup = types.InlineKeyboardMarkup(row_width=1)

    if has_active_chat:
        markup.add(
            types.InlineKeyboardButton(
                "💬 Чат активен ещё " + str(chat_hours_left) + "ч — пиши в бот!",
                callback_data="noop"
            )
        )
    else:
        markup.add(
            types.InlineKeyboardButton(
                "💬 Начать чат ($" + str(int(CHAT_PRICE_USD)) + "/24ч)",
                callback_data="start_chat_" + str(model_id)
            )
        )

    markup.add(
        types.InlineKeyboardButton(
            "📸 Смотреть фото",
            callback_data="girl_full_" + str(model_id)
        )
    )
    markup.add(types.InlineKeyboardButton("« Назад к каталогу", callback_data="girls"))
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu"))
    return markup


def get_back_to_catalog_keyboard(model_id: int) -> types.InlineKeyboardMarkup:
    """Кнопки навигации после просмотра медиа"""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(
            "« Профиль",
            callback_data="girl_" + str(model_id)
        ),
        types.InlineKeyboardButton(
            "📋 Каталог",
            callback_data="girls"
        )
    )
    markup.add(
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")
    )
    return markup


# ─────────────────────────────────────────────
# Показ страницы каталога (вынесено в отдельную функцию)
# ─────────────────────────────────────────────

def show_catalog(bot, chat_id: int, message_id: int,
                 user_id: int, page: int = 0, edit: bool = True):
    """
    Показывает страницу каталога моделей.

    Args:
        bot:        экземпляр бота
        chat_id:    id чата
        message_id: id сообщения для редактирования
        user_id:    id пользователя
        page:       номер страницы (с 0)
        edit:       True → edit_message_text, False → send_message
    """
    all_models = get_all_models()

    if not all_models:
        text = "😔 Моделей пока нет. Скоро появятся!"
        if edit:
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text
                )
            except Exception:
                bot.send_message(chat_id, text)
        else:
            bot.send_message(chat_id, text)
        return

    # Пагинация
    total_pages = max(1, (len(all_models) + MODELS_PER_PAGE - 1) // MODELS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))  # Ограничиваем диапазон

    start = page * MODELS_PER_PAGE
    end = start + MODELS_PER_PAGE
    page_models = all_models[start:end]

    page_info = ""
    if total_pages > 1:
        page_info = "📄 Страница " + str(page + 1) + " из " + str(total_pages) + "\n"

    text = (
        "👭 Каталог Miss Moldova\n"
        "━━━━━━━━━━━━━━━\n"
        "🔥 " + str(len(all_models)) + " девушек в клубе\n"
        + page_info +
        "━━━━━━━━━━━━━━━\n\n"
        "Выбери девушку 👇"
    )

    keyboard = get_girls_list_keyboard(page_models, page, total_pages)

    if edit:
        # Стратегия: сначала пробуем edit_message_text (быстро, без мигания).
        # Если сообщение содержит фото/медиа (caption вместо text) —
        # Telegram вернёт 400 "there is no text in the message to edit".
        # В этом случае удаляем старое сообщение и отправляем новое текстовое.
        # Именно это происходит при возврате из профиля модели с фото.
        edited = False
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard
            )
            edited = True
        except Exception as e:
            err = str(e).lower()
            if (
                "there is no text" in err
                or "message can't be edited" in err
                or "message to edit not found" in err
                or "bad request" in err
            ):
                # Сообщение с медиа — удаляем и шлём текстовое
                edited = False
            else:
                print("[CATALOG ERROR] " + str(e))
                edited = False

        if not edited:
            try:
                bot.delete_message(chat_id, message_id)
            except Exception:
                pass
            bot.send_message(chat_id, text, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


# ─────────────────────────────────────────────
# Регистрация хендлеров
# ─────────────────────────────────────────────

def register_girls_handlers(bot):

    # ── Каталог — первая страница ────────────

    @bot.callback_query_handler(func=lambda call: call.data == "girls")
    def girls_catalog(call):
        """Показывает первую страницу каталога"""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )
        show_catalog(
            bot,
            call.message.chat.id,
            call.message.message_id,
            user_id,
            page=0,
            edit=True
        )

    # ── Пагинация — переход на конкретную страницу ──

    @bot.callback_query_handler(func=lambda call: call.data.startswith("girls_page_"))
    def girls_page(call):
        """Переход на указанную страницу каталога"""
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        try:
            page = int(call.data.replace("girls_page_", ""))
        except ValueError:
            page = 0
        show_catalog(
            bot,
            call.message.chat.id,
            call.message.message_id,
            user_id,
            page=page,
            edit=True
        )

    # ── Заглушка для кнопки-счётчика страниц ──

    @bot.callback_query_handler(func=lambda call: call.data == "noop")
    def noop_handler(call):
        """Кнопка без действия — счётчик страниц"""
        bot.answer_callback_query(call.id)

    # ── Профиль конкретной модели ────────────

    @bot.callback_query_handler(
        func=lambda call: (
            call.data.startswith("girl_")
            and not call.data.startswith("girl_preview_")
            and not call.data.startswith("girl_full_")
        )
    )
    def girl_profile(call):
        """
        Показывает профиль выбранной модели.
        ИСПРАВЛЕНО: удаляем текущее сообщение и отправляем новое —
        это решает проблему с кнопкой Назад (нельзя edit фото-сообщение как текст).
        """
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_", ""))
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
            return

        model = get_model(model_id)
        if not model:
            bot.answer_callback_query(call.id, "❌ Модель не найдена", show_alert=True)
            return

        active_chat = get_active_chat(user_id, model_id)
        has_active_chat = active_chat is not None
        chat_hours_left = 0
        if active_chat:
            remaining = max(0, active_chat["expires_at"] - int(time.time()))
            chat_hours_left = remaining // 3600

        if has_active_chat:
            access_label = "💬 Чат активен ещё " + str(chat_hours_left) + "ч"
        else:
            access_label = "💬 Чат — $" + str(int(CHAT_PRICE_USD)) + "/24ч"

        age = model.get("age", "?")

        text = (
            "👩 " + model["name"] + " | " + str(age) + " лет\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📝 " + (model.get("description") or "Описание скоро появится") + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🎯 " + access_label
        )

        keyboard = get_girl_profile_keyboard(model_id, has_active_chat, chat_hours_left)
        preview_photo  = model.get("preview_photo")
        preview_photo2 = model.get("preview_photo_2")

        if preview_photo:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass

            if preview_photo2:
                # Две аватарки: первое фото без подписи, второе с текстом и кнопками
                try:
                    bot.send_photo(
                        chat_id=call.message.chat.id,
                        photo=preview_photo
                    )
                except Exception as e:
                    print("[GIRLS] Ошибка фото 1: " + str(e))
                try:
                    bot.send_photo(
                        chat_id=call.message.chat.id,
                        photo=preview_photo2,
                        caption=text,
                        reply_markup=keyboard
                    )
                except Exception as e:
                    print("[GIRLS] Ошибка фото 2: " + str(e))
                    bot.send_message(
                        chat_id=call.message.chat.id,
                        text=text,
                        reply_markup=keyboard
                    )
            else:
                # Одна аватарка — фото с подписью и клавиатурой
                try:
                    bot.send_photo(
                        chat_id=call.message.chat.id,
                        photo=preview_photo,
                        caption=text,
                        reply_markup=keyboard
                    )
                except Exception as e:
                    print("[GIRLS] Ошибка отправки фото профиля: " + str(e))
                    bot.send_message(
                        chat_id=call.message.chat.id,
                        text=text,
                        reply_markup=keyboard
                    )
        else:
            # Нет фото — редактируем текст
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=text,
                    reply_markup=keyboard
                )
            except Exception as e:
                err = str(e).lower()
                if "there is no text" in err or "message can't be edited" in err:
                    try:
                        bot.delete_message(call.message.chat.id, call.message.message_id)
                    except Exception:
                        pass
                    bot.send_message(call.message.chat.id, text, reply_markup=keyboard)
                else:
                    print("[GIRLS] edit_message_text error: " + str(e))

    # ── Начать чат с моделью ─────────────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("start_chat_")
    )
    def start_chat(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("start_chat_", ""))
        except ValueError:
            return

        model = get_model(model_id)
        if not model:
            bot.answer_callback_query(call.id, "❌ Модель не найдена", show_alert=True)
            return

        try:
            session = activate_day_chat(user_id, model_id)
        except InsufficientBalanceError:
            balance = get_usd_balance(user_id)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("💵 Пополнить баланс", callback_data="topup_balance"),
                types.InlineKeyboardButton("« Назад",             callback_data="girls")
            )
            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=(
                        "❌ Недостаточно средств\n\n"
                        "Баланс: $" + str(round(balance, 2)) + "\n"
                        "Нужно: $" + str(int(CHAT_PRICE_USD)) + "\n\n"
                        "Пополни баланс и возвращайся!"
                    ),
                    reply_markup=markup
                )
            except Exception:
                bot.send_message(
                    call.message.chat.id,
                    "❌ Недостаточно средств. Пополни баланс.",
                    reply_markup=markup
                )
            return
        except ActiveChatExistsError:
            bot.answer_callback_query(
                call.id,
                "💬 Чат уже активен! Просто пиши в этот чат.",
                show_alert=True
            )
            return
        except Exception as e:
            print("[START_CHAT] Ошибка: " + str(e))
            bot.answer_callback_query(call.id, "❌ Ошибка. Попробуй позже.", show_alert=True)
            return

        # Уведомить модель
        try:
            bot.send_message(
                model_id,
                "💌 Новый фанат открыл чат на 24ч!\n\n"
                "Пиши прямо сюда — сообщения дойдут до него."
            )
        except Exception as e:
            print("[START_CHAT] Не удалось уведомить модель: " + str(e))

        hours_left = max(0, session["expires_at"] - int(time.time())) // 3600
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("« Назад к каталогу", callback_data="girls"),
            types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")
        )
        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=(
                    "✅ Чат с " + model["name"] + " открыт!\n\n"
                    "⏰ Активен ещё " + str(hours_left) + " часов\n"
                    "💵 Списано: $" + str(int(CHAT_PRICE_USD)) + "\n\n"
                    "Пиши прямо в этот бот — "
                    "сообщения дойдут до модели 💬"
                ),
                reply_markup=markup
            )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                "✅ Чат открыт! Пиши прямо в этот бот.",
                reply_markup=markup
            )

    # ── Фото/видео модели (бесплатный просмотр) ──

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("girl_full_")
    )
    def girl_full_content(call):
        """Показывает все фото и видео модели."""
        bot.answer_callback_query(call.id, "📸 Загружаю...")
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_full_", ""))
        except ValueError:
            return

        model = get_model(model_id)
        if not model:
            return

        all_media = get_all_media(model_id)

        if not all_media:
            bot.send_message(call.message.chat.id, "😔 Контент пока не добавлен")
            return

        photos = [m for m in all_media if m["media_type"] == "photo"]
        videos = [m for m in all_media if m["media_type"] == "video"]

        header = (
            "👑 Premium контент — " + model["name"] + "\n"
            "📸 " + str(len(photos)) + " фото"
        )
        if videos:
            header += " | 🎥 " + str(len(videos)) + " видео"

        for i, media in enumerate(all_media):
            caption = header if i == 0 else None
            try:
                if media["media_type"] == "photo":
                    bot.send_photo(
                        chat_id=call.message.chat.id,
                        photo=media["file_id"],
                        caption=caption
                    )
                elif media["media_type"] == "video":
                    bot.send_video(
                        chat_id=call.message.chat.id,
                        video=media["file_id"],
                        caption=caption
                    )
            except Exception as e:
                print("[GIRLS] Ошибка медиа #" + str(i) + ": " + str(e))
            time.sleep(0.3)

        bot.send_message(
            chat_id=call.message.chat.id,
            text=(
                "━━━━━━━━━━━━━━━\n"
                "✅ Фото " + model["name"] + " загружены\n\n"
                "💬 Хочешь пообщаться? Купи чат за $" + str(int(CHAT_PRICE_USD)) + "!"
            ),
            reply_markup=get_back_to_catalog_keyboard(model_id)
        )
