# handlers/girls.py
# Каталог моделей — просмотр профилей, превью и премиум контент
# Исправлено:
# 1. Кнопка «Назад к каталогу» — удаляем фото-сообщение, показываем каталог
# 2. Пагинация в каталоге (5 моделей на странице)
# 3. Возраст берётся из _enrich_model() → calculate_age() динамически

from telebot import types
from database import (
    register_user,
    check_subscription
)
from database.models import (
    get_all_models,
    get_model,
    get_preview_media,
    get_all_media
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


def get_girl_profile_keyboard(model_id: int, has_premium: bool, has_fan: bool) -> types.InlineKeyboardMarkup:
    """
    Клавиатура профиля модели.
    has_premium — полный доступ, has_fan — только превью.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)

    if has_premium:
        markup.add(
            types.InlineKeyboardButton(
                "🔓 Смотреть весь контент",
                callback_data="girl_full_" + str(model_id)
            )
        )
    elif has_fan:
        markup.add(
            types.InlineKeyboardButton(
                "👁 Смотреть превью (Fan)",
                callback_data="girl_preview_" + str(model_id)
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "👑 Получить Premium доступ",
                callback_data="subscription"
            )
        )
    else:
        markup.add(
            types.InlineKeyboardButton(
                "👁 Превью (нужна Fan/Premium)",
                callback_data="girl_preview_" + str(model_id)
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "💎 Оформить подписку",
                callback_data="subscription"
            )
        )

    # Кнопка Назад — всегда возвращает на первую страницу каталога
    markup.add(
        types.InlineKeyboardButton("« Назад к каталогу", callback_data="girls")
    )
    markup.add(
        types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")
    )
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

    sub = check_subscription(user_id)

    if sub["active"]:
        sub_type_val = sub.get("type") or ""
        if "premium" in sub_type_val or sub_type_val == "test_2min":
            access_text = "👑 У тебя Premium — полный доступ!"
        else:
            access_text = "🌸 У тебя Fan — превью профилей"
    else:
        access_text = "🔒 Нет подписки — только превью"

    page_info = ""
    if total_pages > 1:
        page_info = "📄 Страница " + str(page + 1) + " из " + str(total_pages) + "\n"

    text = (
        "👭 Каталог Miss Moldova\n"
        "━━━━━━━━━━━━━━━\n"
        "🔥 " + str(len(all_models)) + " девушек в клубе\n"
        + page_info +
        "📍 " + access_text + "\n"
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

        sub = check_subscription(user_id)
        sub_type = sub.get("type") or ""
        has_premium = sub["active"] and ("premium" in sub_type or sub_type == "test_2min")
        has_fan = sub["active"] and not has_premium

        if has_premium:
            access_label = "👑 Полный доступ"
        elif has_fan:
            access_label = "🌸 Fan — превью доступно"
        else:
            access_label = "🔒 Нужна подписка"

        age = model.get("age", "?")

        text = (
            "👩 " + model["name"] + " | " + str(age) + " лет\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📝 " + (model.get("description") or "Описание скоро появится") + "\n\n"
            "📱 " + ("@" + model["username"] if model.get("username") else "Контакт скрыт") + "\n"
            "━━━━━━━━━━━━━━━\n"
            "🎯 " + access_label
        )

        keyboard = get_girl_profile_keyboard(model_id, has_premium, has_fan)
        preview_photo = model.get("preview_photo")

        if preview_photo:
            # Удаляем старое (текстовое) сообщение, отправляем фото с профилем
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            try:
                bot.send_photo(
                    chat_id=call.message.chat.id,
                    photo=preview_photo,
                    caption=text,
                    reply_markup=keyboard
                )
            except Exception as e:
                print("[GIRLS] Ошибка отправки фото профиля: " + str(e))
                # Fallback — текстовое сообщение
                bot.send_message(
                    chat_id=call.message.chat.id,
                    text=text,
                    reply_markup=keyboard
                )
        else:
            # Нет фото — просто редактируем текст
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

    # ── Превью для Fan подписки ──────────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("girl_preview_")
    )
    def girl_preview(call):
        """
        Показывает 3 превью фото.
        Для Fan и Premium подписок.
        """
        bot.answer_callback_query(call.id, "🌸 Загружаю превью...")
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_preview_", ""))
        except ValueError:
            return

        sub = check_subscription(user_id)

        if not sub["active"]:
            bot.answer_callback_query(
                call.id,
                "🔒 Нужна Fan или Premium подписка!\n\nОформи в меню 💎",
                show_alert=True
            )
            return

        model = get_model(model_id)
        if not model:
            return

        preview_media = get_preview_media(model_id)

        if not preview_media:
            bot.send_message(
                call.message.chat.id,
                "😔 Превью пока не добавлено"
            )
            return

        # Отправляем превью фото по одному
        for i, media in enumerate(preview_media):
            caption = None
            if i == 0:
                caption = (
                    "🌸 Превью — " + model["name"] + "\n"
                    "📸 " + str(len(preview_media)) + " фото\n\n"
                    "👑 Хочешь больше? Оформи Premium!"
                )
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
                print("[GIRLS] Ошибка превью: " + str(e))

        bot.send_message(
            chat_id=call.message.chat.id,
            text=(
                "━━━━━━━━━━━━━━━\n"
                "👆 Превью " + model["name"] + "\n\n"
                "Полный контент доступен по Premium 👑"
            ),
            reply_markup=get_back_to_catalog_keyboard(model_id)
        )

    # ── Полный контент для Premium ───────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("girl_full_")
    )
    def girl_full_content(call):
        """Показывает весь контент модели. Только Premium."""
        bot.answer_callback_query(call.id, "🔓 Загружаю контент...")
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_full_", ""))
        except ValueError:
            return

        sub = check_subscription(user_id)

        sub_type = sub.get("type") or ""
        if not sub["active"] or ("premium" not in sub_type and sub_type != "test_2min"):
            bot.answer_callback_query(
                call.id,
                "👑 Только для Premium подписчиков!\n\nОформи Premium в меню 💎",
                show_alert=True
            )
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

        bot.send_message(
            chat_id=call.message.chat.id,
            text=(
                "━━━━━━━━━━━━━━━\n"
                "✅ Весь контент " + model["name"] + " загружен\n\n"
                "🔥 Новый контент выходит каждую неделю!"
            ),
            reply_markup=get_back_to_catalog_keyboard(model_id)
        )

    # ── Написать девушке ─────────────────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("contact_girl_")
    )
    def contact_girl(call):
        """Запрос на знакомство — уведомляет админа, показывает попап."""
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("contact_girl_", ""))
        except ValueError:
            bot.answer_callback_query(call.id)
            return

        sub = check_subscription(user_id)
        if not sub["active"]:
            bot.answer_callback_query(
                call.id,
                "🔒 Для связи с девушками нужна подписка\n\nОформи Fan или Premium 💎",
                show_alert=True
            )
            return

        model = get_model(model_id)
        if not model:
            bot.answer_callback_query(call.id)
            return

        bot.answer_callback_query(
            call.id,
            "💌 Запрос принят!\n\n"
            "Администрация Miss Moldova свяжется с тобой в ближайшее время.\n\n"
            "Ожидай сообщения ❤️",
            show_alert=True
        )

        username = call.from_user.username
        full_name = call.from_user.full_name or "Пользователь"
        user_ref = "@" + username if username else full_name
        sub_type = sub.get("type") or ""
        sub_name = "👑 Premium" if "premium" in sub_type else "🌸 Fan"

        from config import ADMIN_IDS
        reply_keyboard = types.InlineKeyboardMarkup()
        reply_keyboard.add(
            types.InlineKeyboardButton(
                "💬 Написать пользователю",
                callback_data="admin_reply_" + str(user_id)
            )
        )

        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    "💌 Новый запрос на знакомство!\n"
                    "━━━━━━━━━━━━━━━\n\n"
                    "👤 Пользователь: " + user_ref + "\n"
                    "🆔 ID: " + str(user_id) + "\n"
                    "💳 Подписка: " + sub_name + "\n\n"
                    "💕 Интересует: " + model["name"] + "\n\n"
                    "━━━━━━━━━━━━━━━",
                    reply_markup=reply_keyboard
                )
            except Exception as e:
                print("[CONTACT] Ошибка уведомления: " + str(e))

        notify_channel(
            bot,
            "💌 Запрос на знакомство\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 " + user_ref + "\n"
            "🆔 ID: " + str(user_id) + "\n"
            "💳 Подписка: " + sub_name + "\n"
            "💕 Интересует: " + model["name"]
        )
