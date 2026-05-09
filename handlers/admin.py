# handlers/admin.py
from telebot import types
from config import ADMIN_IDS, MEDIA_CHANNEL_ID
from database.models import (
    add_model,
    get_all_models,
    get_model,
    add_model_media,
    set_preview_photo,
    deactivate_model,
    get_preview_media,
    get_all_media
)

admin_states = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def register_admin_handlers(bot):

    @bot.message_handler(commands=['admin'])
    def admin_panel(message):
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ Нет доступа")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("👩 Добавить модель", callback_data="admin_add_model"),
            types.InlineKeyboardButton("📋 Список моделей", callback_data="admin_list_models"),
            types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")
        )

        bot.send_message(
            message.chat.id,
            "👑 Админ панель Miss Moldova\n\nВыбери действие:",
            reply_markup=markup
        )

    @bot.message_handler(commands=['addmodel'])
    def add_model_command(message):
        if not is_admin(message.from_user.id):
            return

        bot.send_message(
            message.chat.id,
            "👩 Добавление новой модели\n\n"
            "Отправь данные в формате:\n"
            "Имя | Возраст | Ник | Описание\n\n"
            "Пример:\n"
            "Марина | 24 | marina_moldova | Нежная и страстная 🔥"
        )
        admin_states[message.from_user.id] = "waiting_model_data"

    @bot.message_handler(commands=['models'])
    def list_models_command(message):
        if not is_admin(message.from_user.id):
            return

        models = get_all_models()

        if not models:
            bot.send_message(message.chat.id, "📋 Моделей пока нет")
            return

        text = "📋 Список моделей:\n\n"
        for model in models:
            text += (
                "👩 " + model["name"] + " | " +
                str(model["age"]) + " лет\n"
                "ID: " + str(model["id"]) + "\n"
                "@" + (model["username"] or "нет") + "\n\n"
            )

        bot.send_message(message.chat.id, text)

    @bot.message_handler(
        func=lambda msg: admin_states.get(msg.from_user.id) == "waiting_model_data"
    )
    def process_model_data(message):
        if not is_admin(message.from_user.id):
            return

        try:
            parts = [p.strip() for p in message.text.split("|")]

            if len(parts) < 4:
                bot.send_message(
                    message.chat.id,
                    "❌ Неверный формат!\n"
                    "Нужно: Имя | Возраст | Ник | Описание"
                )
                return

            name = parts[0]
            age = int(parts[1])
            username = parts[2]
            description = parts[3]

            model_id = add_model(name, age, username, description)

            admin_states[message.from_user.id] = "waiting_preview_photo_" + str(model_id)

            bot.send_message(
                message.chat.id,
                "✅ Модель добавлена!\n\n"
                "👩 Имя: " + name + "\n"
                "🎂 Возраст: " + str(age) + "\n"
                "📱 Ник: @" + username + "\n"
                "🆔 ID модели: " + str(model_id) + "\n\n"
                "Теперь отправь главное фото профиля (превью):"
            )

        except ValueError:
            bot.send_message(message.chat.id, "❌ Возраст должен быть числом!")
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Ошибка: " + str(e))

    @bot.message_handler(
        content_types=['photo'],
        func=lambda msg: any(
            str(admin_states.get(msg.from_user.id, "")).startswith(p)
            for p in ["waiting_preview_photo_", "waiting_media_"]
        )
    )
    def process_model_photo(message):
        if not is_admin(message.from_user.id):
            return

        state = admin_states.get(message.from_user.id, "")
        file_id = message.photo[-1].file_id

        if state.startswith("waiting_preview_photo_"):
            model_id = int(state.replace("waiting_preview_photo_", ""))

            set_preview_photo(model_id, file_id)
            add_model_media(model_id, file_id, 'photo', is_preview=1, position=1)

            admin_states[message.from_user.id] = "waiting_media_" + str(model_id)

            bot.send_message(
                message.chat.id,
                "✅ Главное фото сохранено!\n\n"
                "Теперь отправляй остальные фото/видео.\n"
                "Первые 3 фото — превью для Fan подписки.\n"
                "Все остальные — только для Premium.\n\n"
                "Когда закончишь — напиши /done"
            )

        elif state.startswith("waiting_media_"):
            model_id = int(state.replace("waiting_media_", ""))

            existing = get_all_media(model_id)
            position = len(existing) + 1
            is_preview = 1 if position <= 3 else 0

            add_model_media(model_id, file_id, 'photo', is_preview, position)

            preview_text = "👁 Fan превью" if is_preview else "🔒 Premium контент"

            bot.send_message(
                message.chat.id,
                "✅ Фото " + str(position) + " добавлено — " + preview_text + "\n"
                "Отправляй следующее или /done"
            )

    @bot.message_handler(
        content_types=['video'],
        func=lambda msg: str(admin_states.get(msg.from_user.id, "")).startswith("waiting_media_")
    )
    def process_model_video(message):
        if not is_admin(message.from_user.id):
            return

        state = admin_states.get(message.from_user.id, "")
        model_id = int(state.replace("waiting_media_", ""))
        file_id = message.video.file_id

        existing = get_all_media(model_id)
        position = len(existing) + 1

        add_model_media(model_id, file_id, 'video', is_preview=0, position=position)

        bot.send_message(
            message.chat.id,
            "✅ Видео " + str(position) + " добавлено — 🔒 Premium контент\n"
            "Отправляй следующее или /done"
        )

    @bot.message_handler(commands=['done'])
    def done_adding_media(message):
        if not is_admin(message.from_user.id):
            return

        state = admin_states.get(message.from_user.id, "")

        if not state.startswith("waiting_media_"):
            bot.send_message(message.chat.id, "❌ Нет активной загрузки")
            return

        model_id = int(state.replace("waiting_media_", ""))
        model = get_model(model_id)

        if not model:
            return

        all_media = get_all_media(model_id)
        preview_media = get_preview_media(model_id)

        del admin_states[message.from_user.id]

        bot.send_message(
            message.chat.id,
            "🎉 Модель успешно добавлена!\n\n"
            "👩 Имя: " + model["name"] + "\n"
            "🎂 Возраст: " + str(model["age"]) + "\n"
            "📱 Ник: @" + (model["username"] or "нет") + "\n\n"
            "📸 Всего медиа: " + str(len(all_media)) + "\n"
            "👁 Превью Fan: " + str(len(preview_media)) + " фото\n"
            "🔒 Premium: " + str(len(all_media) - len(preview_media)) + " файлов"
        )

    @bot.callback_query_handler(func=lambda call: call.data == "admin_add_model")
    def admin_add_model_callback(call):
        if not is_admin(call.from_user.id):
            return
        bot.send_message(
            call.message.chat.id,
            "👩 Отправь данные модели:\n"
            "Имя | Возраст | Ник | Описание"
        )
        admin_states[call.from_user.id] = "waiting_model_data"

    @bot.callback_query_handler(func=lambda call: call.data == "admin_list_models")
    def admin_list_models_callback(call):
        if not is_admin(call.from_user.id):
            return

        models = get_all_models()
        if not models:
            bot.answer_callback_query(call.id, "Моделей пока нет")
            return

        text = "📋 Список моделей:\n\n"
        for model in models:
            text += "👩 " + model["name"] + " | " + str(model["age"]) + " лет | ID: " + str(model["id"]) + "\n"

        bot.send_message(call.message.chat.id, text)

    @bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
    def admin_stats_callback(call):
        if not is_admin(call.from_user.id):
            return

        from database import get_connection
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users WHERE subscription_type IS NOT NULL")
        subscribed = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'confirmed'")
        payments = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM models WHERE is_active = 1")
        models_count = cursor.fetchone()[0]

        conn.close()

        bot.send_message(
            call.message.chat.id,
            "📊 Статистика Miss Moldova\n\n"
            "👥 Всего пользователей: " + str(total_users) + "\n"
            "💎 С подпиской: " + str(subscribed) + "\n"
            "💰 Платежей подтверждено: " + str(payments) + "\n"
            "👩 Активных моделей: " + str(models_count)
        )
