# handlers/girls.py
# Каталог моделей — просмотр профилей, превью и премиум контент
# Доступ зависит от типа подписки пользователя

from telebot import types
from database import (
    register_user,
    get_user,
    check_subscription,
    spend_crystals
)
from database.models import (
    get_all_models,
    get_model,
    get_preview_media,
    get_all_media
)


# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def get_girls_list_keyboard(models: list) -> types.InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком моделей.
    Каждая кнопка — отдельная девушка.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)
    for model in models:
        label = (
            "👩 " + model["name"] +
            " | " + str(model["age"]) + " лет"
        )
        markup.add(
            types.InlineKeyboardButton(
                label,
                callback_data="girl_" + str(model["id"])
            )
        )
    markup.add(
        types.InlineKeyboardButton("« Главное меню", callback_data="back_to_menu")
    )
    return markup


def get_girl_profile_keyboard(model_id: int, has_access: bool) -> types.InlineKeyboardMarkup:
    """
    Клавиатура профиля модели.
    has_access — True если у пользователя Premium подписка.
    """
    markup = types.InlineKeyboardMarkup(row_width=1)

    if has_access:
        # Пользователь видит кнопку полного контента
        markup.add(
            types.InlineKeyboardButton(
                "🔓 Смотреть весь контент",
                callback_data="girl_full_" + str(model_id)
            )
        )
    else:
        # Показываем превью и предложение подписки
        markup.add(
            types.InlineKeyboardButton(
                "👁 Смотреть превью (Fan)",
                callback_data="girl_preview_" + str(model_id)
            ),
            types.InlineKeyboardButton(
                "👑 Получить Premium доступ",
                callback_data="subscription"
            )
        )

    markup.add(
        types.InlineKeyboardButton("« Назад к каталогу", callback_data="girls")
    )
    return markup


def get_back_to_catalog_keyboard(model_id: int) -> types.InlineKeyboardMarkup:
    """Кнопка возврата после просмотра медиа"""
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
    return markup


# ─────────────────────────────────────────────
# Регистрация хендлеров
# ─────────────────────────────────────────────

def register_girls_handlers(bot):

    # ── Каталог девушек ──────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "girls")
    def girls_catalog(call):
        """Показывает список всех активных моделей"""
        user_id = call.from_user.id

        # Регистрируем пользователя если новый
        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )

        models = get_all_models()

        if not models:
            bot.answer_callback_query(
                call.id,
                "😔 Моделей пока нет. Скоро появятся!",
                show_alert=True
            )
            return

        sub = check_subscription(user_id)

        # Заголовок меняется в зависимости от подписки
        if sub["active"]:
            if "premium" in sub["type"]:
                access_text = "👑 У тебя Premium — полный доступ!"
            else:
                access_text = "🌸 У тебя Fan — превью профилей"
        else:
            access_text = "🔒 Нет подписки — только превью"

        text = (
            "👭 Каталог Miss Moldova\n"
            "━━━━━━━━━━━━━━━\n"
            "🔥 " + str(len(models)) + " девушек в клубе\n"
            "📍 " + access_text + "\n"
            "━━━━━━━━━━━━━━━\n\n"
            "Выбери девушку 👇"
        )

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_girls_list_keyboard(models)
        )

    # ── Профиль конкретной модели ────────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("girl_") and
        not call.data.startswith("girl_preview_") and
        not call.data.startswith("girl_full_")
    )
    def girl_profile(call):
        """Показывает профиль выбранной модели"""
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_", ""))
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
            return

        model = get_model(model_id)
        if not model:
            bot.answer_callback_query(
                call.id,
                "❌ Модель не найдена",
                show_alert=True
            )
            return

        sub = check_subscription(user_id)
        has_premium = sub["active"] and "premium" in sub.get("type", "")
        has_fan = sub["active"] and not has_premium

        # Определяем уровень доступа для текста
        if has_premium:
            access_label = "👑 Полный доступ"
        elif has_fan:
            access_label = "🌸 Fan — превью доступно"
        else:
            access_label = "🔒 Нужна подписка"

        text = (
            "👩 " + model["name"] + " | " + str(model["age"]) + " лет\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📝 " + (model.get("description") or "Описание скоро появится") + "\n\n"
            "📱 " + ("@" + model["username"] if model.get("username") else "Контакт скрыт") + "\n"
            "━━━━━━━━━━━━━━━\n"
            "🎯 " + access_label
        )

        # Если есть главное фото профиля — отправляем с фото
        preview_photo = model.get("preview_photo")

        if preview_photo:
            try:
                # Удаляем старое сообщение и отправляем фото с профилем
                bot.delete_message(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id
                )
                bot.send_photo(
                    chat_id=call.message.chat.id,
                    photo=preview_photo,
                    caption=text,
                    reply_markup=get_girl_profile_keyboard(model_id, has_premium)
                )
            except Exception as e:
                print("[GIRLS] Ошибка отправки фото профиля: " + str(e))
                # Fallback — текстовое сообщение
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=text,
                    reply_markup=get_girl_profile_keyboard(model_id, has_premium)
                )
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=get_girl_profile_keyboard(model_id, has_premium)
            )

    # ── Превью для Fan подписки ──────────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("girl_preview_")
    )
    def girl_preview(call):
        """
        Показывает 3 превью фото для Fan подписки.
        Если нет подписки вообще — отказ.
        """
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_preview_", ""))
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
            return

        sub = check_subscription(user_id)

        # Проверяем наличие хотя бы Fan подписки
        if not sub["active"]:
            bot.answer_callback_query(
                call.id,
                "🔒 Нужна Fan или Premium подписка!\n\nОформи в меню 💎",
                show_alert=True
            )
            return

        model = get_model(model_id)
        if not model:
            bot.answer_callback_query(call.id, "❌ Модель не найдена", show_alert=True)
            return

        preview_media = get_preview_media(model_id)

        if not preview_media:
            bot.answer_callback_query(
                call.id,
                "😔 Превью пока не добавлено",
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id, "🌸 Загружаю превью...")

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
                print("[GIRLS] Ошибка отправки превью: " + str(e))

        # Кнопки после просмотра превью
        bot.send_message(
            chat_id=call.message.chat.id,
            text="━━━━━━━━━━━━━━━\n👆 Превью " + model["name"] + "\n\n"
                 "Полный контент доступен по Premium 👑",
            reply_markup=get_back_to_catalog_keyboard(model_id)
        )

    # ── Полный контент для Premium ───────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("girl_full_")
    )
    def girl_full_content(call):
        """
        Показывает весь контент модели.
        Только для Premium подписки.
        """
        user_id = call.from_user.id

        try:
            model_id = int(call.data.replace("girl_full_", ""))
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
            return

        sub = check_subscription(user_id)

        # Строгая проверка — только Premium
        if not sub["active"] or "premium" not in sub.get("type", ""):
            bot.answer_callback_query(
                call.id,
                "👑 Только для Premium подписчиков!\n\n"
                "Оформи Premium в меню подписок 💎",
                show_alert=True
            )
            return

        model = get_model(model_id)
        if not model:
            bot.answer_callback_query(call.id, "❌ Модель не найдена", show_alert=True)
            return

        all_media = get_all_media(model_id)

        if not all_media:
            bot.answer_callback_query(
                call.id,
                "😔 Контент пока не добавлен",
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id, "🔓 Загружаю контент...")

        # Считаем фото и видео для заголовка
        photos = [m for m in all_media if m["media_type"] == "photo"]
        videos = [m for m in all_media if m["media_type"] == "video"]

        header = (
            "👑 Premium контент — " + model["name"] + "\n"
            "📸 " + str(len(photos)) + " фото"
        )
        if videos:
            header += " | 🎥 " + str(len(videos)) + " видео"

        # Отправляем весь контент по одному
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
                print("[GIRLS] Ошибка отправки медиа #" + str(i) + ": " + str(e))

        # Финальное сообщение с навигацией
        bot.send_message(
            chat_id=call.message.chat.id,
            text=(
                "━━━━━━━━━━━━━━━\n"
                "✅ Весь контент " + model["name"] + " загружен\n\n"
                "🔥 Новый контент выходит каждую неделю!"
            ),
            reply_markup=get_back_to_catalog_keyboard(model_id)
        )
