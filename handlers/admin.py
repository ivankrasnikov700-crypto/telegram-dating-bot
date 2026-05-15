# handlers/admin.py
# Админ панель — добавление моделей, редактирование, статистика
# Добавлено:
# 1. Поддержка birth_date при добавлении модели
# 2. Команда /editmodel ID для редактирования профиля
# 3. Команда /delmodel ID для деактивации модели
# 4. Улучшенный вывод статистики

import threading
import time

from telebot import types
from config import ADMIN_IDS, LTC_ADDRESS
from database.models import (
    add_model,
    update_model,
    get_all_models,
    get_model,
    add_model_media,
    set_preview_photo,
    deactivate_model,
    get_preview_media,
    get_all_media,
    calculate_age
)

# Состояния админа: user_id → строка состояния
admin_states = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def register_admin_handlers(bot):

    # ── Проверка каналов ──────────────────────

    @bot.message_handler(commands=['channels'])
    def channels_command(message):
        from config import MEDIA_CHANNEL_ID, ADMIN_CHANNEL_ID
        bot.send_message(
            message.chat.id,
            "📡 Каналы в конфиге:\n\n"
            "📢 Медиа ID: " + str(MEDIA_CHANNEL_ID) + "\n"
            "🔒 Админ ID: " + str(ADMIN_CHANNEL_ID) + "\n\n"
            "Твой ID: " + str(message.from_user.id) + "\n"
            "Ты админ: " + str(is_admin(message.from_user.id))
        )

    # ── Проверка кошелька ─────────────────────

    @bot.message_handler(commands=['wallet'])
    def wallet_command(message):
        if not is_admin(message.from_user.id):
            return
        from config import MEDIA_CHANNEL_ID, ADMIN_CHANNEL_ID
        addr = LTC_ADDRESS or "НЕ ЗАДАН"
        bot.send_message(
            message.chat.id,
            "💳 LTC адрес:\n" + str(addr) + "\n\n"
            "📡 Медиа канал ID: " + str(MEDIA_CHANNEL_ID) + "\n"
            "🔒 Админ канал ID: " + str(ADMIN_CHANNEL_ID)
        )

    # ── Активация любой подписки вручную ─────

    @bot.message_handler(commands=['activate'])
    def activate_command(message):
        """
        Активирует подписку для пользователя без оплаты.
        Использование: /activate USER_ID PLAN
        Планы: fan_30 | premium_90 | test_2min
        Пример: /activate 7406734422 fan_30
        """
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ Нет доступа")
            return

        parts = message.text.split()
        if len(parts) < 3:
            bot.send_message(
                message.chat.id,
                "❌ Использование:\n"
                "/activate USER_ID ПЛАН\n\n"
                "Планы:\n"
                "• fan_30 — Fan 30 дней (250 💎)\n"
                "• premium_90 — Premium 90 дней (600 💎)\n"
                "• test_2min — Тест 2 минуты (10 💎)\n\n"
                "Пример:\n"
                "/activate 7406734422 fan_30"
            )
            return

        if not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ USER_ID должен быть числом")
            return

        target_id = int(parts[1])
        plan = parts[2].lower()

        PLANS = {
            "fan_30":     {"name": "🌸 Fan",    "days": 30,  "minutes": 0, "crystals": 250},
            "premium_90": {"name": "👑 Premium", "days": 90,  "minutes": 0, "crystals": 600},
            "test_2min":  {"name": "🧪 Test",   "days": 0,   "minutes": 2, "crystals": 10},
        }

        if plan not in PLANS:
            bot.send_message(
                message.chat.id,
                "❌ Неизвестный план: " + plan + "\n\n"
                "Доступные: fan_30, premium_90, test_2min"
            )
            return

        p = PLANS[plan]
        from database import register_user, activate_subscription
        register_user(target_id, "", "User")
        activate_subscription(target_id, plan, p["days"], p["crystals"], minutes=p["minutes"])

        if p["minutes"] > 0:
            duration = str(p["minutes"]) + " минуты"
        else:
            duration = str(p["days"]) + " дней"

        bot.send_message(
            message.chat.id,
            "✅ Подписка активирована!\n\n"
            "👤 User ID: " + str(target_id) + "\n"
            "💳 План: " + p["name"] + "\n"
            "⏰ Срок: " + duration + "\n"
            "💎 Кристаллов: " + str(p["crystals"])
        )

        # Уведомляем пользователя
        try:
            from keyboards.inline import get_main_menu
            bot.send_message(
                target_id,
                "✅ Подписка " + p["name"] + " активирована!\n\n"
                "⏰ Срок: " + duration + "\n"
                "💎 Начислено: " + str(p["crystals"]) + " кристаллов\n\n"
                "Добро пожаловать в клуб! ❤️",
                reply_markup=get_main_menu()
            )
        except Exception as e:
            print("[ACTIVATE] Не удалось уведомить: " + str(e))

        # Для теста — запускаем уведомление об истечении
        if p["minutes"] > 0:
            def _expire():
                time.sleep(p["minutes"] * 60)
                from database import check_subscription
                if not check_subscription(target_id)["active"]:
                    try:
                        from keyboards.inline import get_subscription_menu
                        bot.send_message(
                            target_id,
                            "⏰ Тестовая подписка истекла!\n\n"
                            "Полный цикл работает корректно ✅",
                            reply_markup=get_subscription_menu()
                        )
                    except Exception as e:
                        print("[ACTIVATE EXPIRY] " + str(e))
            threading.Thread(target=_expire, daemon=True).start()

    # ── Тестовая активация подписки ──────────

    @bot.message_handler(commands=['testactivate'])
    def test_activate_command(message):
        """
        Прямая активация test_2min без оплаты — только для тестирования.
        Использование: /testactivate [user_id]
        Без user_id — активирует себе.
        УДАЛИТЬ перед продакшном вместе с тестовой подпиской.
        """
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ Нет доступа")
            return

        parts = message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            target_id = int(parts[1])
        else:
            target_id = message.from_user.id

        from database import register_user, activate_subscription
        register_user(target_id, "", "Test User")
        activate_subscription(target_id, "test_2min", 0, 10, minutes=2)

        bot.send_message(
            message.chat.id,
            "✅ Тестовая подписка активирована!\n\n"
            "👤 User ID: " + str(target_id) + "\n"
            "⏱ Срок: 2 минуты\n"
            "💎 Начислено: 10 кристаллов\n\n"
            "Уведомление об истечении придёт через 2 мин ⏰"
        )

        # Уведомляем пользователя что подписка активна
        if target_id != message.from_user.id:
            try:
                from keyboards.inline import get_main_menu
                bot.send_message(
                    target_id,
                    "✅ Тестовая Premium подписка активирована!\n\n"
                    "⏱ Срок: 2 минуты\n"
                    "💎 Начислено: 10 кристаллов\n\n"
                    "Проверь профиль чтобы убедиться 👇",
                    reply_markup=get_main_menu()
                )
            except Exception as e:
                print("[TESTACTIVATE] Не удалось уведомить user: " + str(e))

        # Запускаем уведомление об истечении
        def _expiry_notify():
            time.sleep(2 * 60)
            from database import check_subscription
            sub = check_subscription(target_id)
            if not sub["active"]:
                try:
                    from keyboards.inline import get_subscription_menu
                    notify_chat = target_id if target_id != message.from_user.id else message.chat.id
                    bot.send_message(
                        notify_chat,
                        "⏰ Тестовая подписка истекла!\n\n"
                        "Полный цикл работает корректно ✅\n\n"
                        "Готов перейти на боевую подписку? 👇",
                        reply_markup=get_subscription_menu()
                    )
                except Exception as e:
                    print("[TESTACTIVATE EXPIRY] " + str(e))

        threading.Thread(target=_expiry_notify, daemon=True).start()

    # ── Главная панель ───────────────────────

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

    # ── Добавить модель ──────────────────────

    @bot.message_handler(commands=['addmodel'])
    def add_model_command(message):
        if not is_admin(message.from_user.id):
            return

        bot.send_message(
            message.chat.id,
            "👩 Добавление новой модели\n\n"
            "Отправь данные в формате:\n"
            "Имя | Дата рождения или Возраст | Описание\n\n"
            "Примеры:\n"
            "Марина | 15.05.1998 | Нежная и страстная 🔥\n"
            "Анна | 24 | Яркая красавица ✨\n\n"
            "Дата рождения — возраст будет обновляться автоматически!"
        )
        admin_states[message.from_user.id] = "waiting_model_data"

    # ── Список моделей ───────────────────────

    @bot.message_handler(commands=['models'])
    def list_models_command(message):
        if not is_admin(message.from_user.id):
            return

        models = get_all_models()

        if not models:
            bot.send_message(message.chat.id, "📋 Моделей пока нет")
            return

        lines = ["📋 Список моделей:\n"]
        for model in models:
            birth_info = ""
            if model.get("birth_date"):
                birth_info = " (ДР: " + model["birth_date"] + ")"
            lines.append(
                "👩 " + model["name"] + " | " + str(model["age"]) + " лет" + birth_info + "\n"
                "ID: " + str(model["id"]) + " | @" + (model["username"] or "нет")
            )

        bot.send_message(message.chat.id, "\n\n".join(lines))

    # ── Редактировать модель ─────────────────

    @bot.message_handler(commands=['editmodel'])
    def edit_model_command(message):
        if not is_admin(message.from_user.id):
            return

        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(
                message.chat.id,
                "❌ Укажи ID модели\n\n"
                "Пример: /editmodel 3\n\n"
                "Затем бот спросит что изменить."
            )
            return

        model_id = int(parts[1])
        model = get_model(model_id)

        if not model:
            bot.send_message(message.chat.id, "❌ Модель с ID " + str(model_id) + " не найдена")
            return

        admin_states[message.from_user.id] = "editing_model_" + str(model_id)

        age = model.get("age", "?")
        birth = model.get("birth_date", "не задана")

        bot.send_message(
            message.chat.id,
            "✏️ Редактирование: " + model["name"] + " (ID " + str(model_id) + ")\n\n"
            "Текущие данные:\n"
            "Имя: " + model["name"] + "\n"
            "Возраст: " + str(age) + " лет\n"
            "Дата рождения: " + str(birth) + "\n"
            "Описание: " + (model.get("description") or "нет") + "\n\n"
            "Отправь новые данные в формате:\n"
            "Имя | Дата/Возраст | Описание\n\n"
            "Чтобы оставить поле без изменений — напиши точку:\n"
            ". | 12.03.1999 | Новое описание"
        )

    # ── Деактивировать модель ────────────────

    @bot.message_handler(commands=['delmodel'])
    def del_model_command(message):
        if not is_admin(message.from_user.id):
            return

        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /delmodel 3")
            return

        model_id = int(parts[1])
        model = get_model(model_id)

        if not model:
            bot.send_message(message.chat.id, "❌ Модель не найдена")
            return

        deactivate_model(model_id)
        bot.send_message(
            message.chat.id,
            "✅ Модель " + model["name"] + " (ID " + str(model_id) + ") деактивирована.\n"
            "Она скрыта из каталога. Данные не удалены."
        )

    # ── Заменить главное фото модели ────────

    @bot.message_handler(commands=['setphoto'])
    def set_photo_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /setphoto 3")
            return
        model_id = int(parts[1])
        model = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель не найдена")
            return
        admin_states[message.from_user.id] = "waiting_preview_photo_" + str(model_id)
        bot.send_message(
            message.chat.id,
            "📸 Отправь новое главное фото для " + model["name"] + ":"
        )

    # ── Добавить медиа к существующей модели ─

    @bot.message_handler(commands=['addmedia'])
    def add_media_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /addmedia 3")
            return
        model_id = int(parts[1])
        model = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель не найдена")
            return
        admin_states[message.from_user.id] = "waiting_media_" + str(model_id)
        all_media = get_all_media(model_id)
        bot.send_message(
            message.chat.id,
            "📎 Добавление медиа к " + model["name"] + "\n\n"
            "Уже загружено: " + str(len(all_media)) + " файлов\n"
            "Первые 3 — Fan превью, остальные — Premium\n\n"
            "Отправляй фото/видео. Готово → /done"
        )

    # ── Завершить загрузку медиа ─────────────

    @bot.message_handler(commands=['done'])
    def done_adding_media(message):
        if not is_admin(message.from_user.id):
            return

        state = admin_states.get(message.from_user.id, "")

        if not state.startswith("waiting_media_"):
            bot.send_message(message.chat.id, "❌ Нет активной загрузки медиа")
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
            "🎂 Возраст: " + str(model["age"]) + " лет\n\n"
            "📸 Всего медиа: " + str(len(all_media)) + "\n"
            "👁 Превью Fan: " + str(len(preview_media)) + " фото\n"
            "🔒 Premium: " + str(len(all_media) - len(preview_media)) + " файлов"
        )

    # ── Ответ пользователю через бота ────────

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("admin_reply_")
    )
    def admin_reply_callback(call):
        if not is_admin(call.from_user.id):
            return
        bot.answer_callback_query(call.id)
        target_id = int(call.data.replace("admin_reply_", ""))
        admin_states[call.from_user.id] = "replying_to_" + str(target_id)
        bot.send_message(
            call.message.chat.id,
            "✍️ Введи сообщение для пользователя:\n\n"
            "Оно придёт от имени бота Miss Moldova ❤️\n\n"
            "/cancel — отменить"
        )

    @bot.message_handler(commands=['cancel'])
    def cancel_reply(message):
        if not is_admin(message.from_user.id):
            return
        state = admin_states.pop(message.from_user.id, "")
        if state.startswith("replying_to_"):
            bot.send_message(message.chat.id, "❌ Отправка отменена")

    @bot.message_handler(
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and str(admin_states.get(msg.from_user.id, "")).startswith("replying_to_")
        )
    )
    def send_reply_to_user(message):
        if not is_admin(message.from_user.id):
            return
        state = admin_states.pop(message.from_user.id, "")
        target_id = int(state.replace("replying_to_", ""))
        try:
            from keyboards.inline import get_main_menu
            bot.send_message(
                target_id,
                "💌 Сообщение от Miss Moldova\n"
                "━━━━━━━━━━━━━━━\n\n"
                + message.text +
                "\n\n━━━━━━━━━━━━━━━\n"
                "Miss Moldova ❤️",
                reply_markup=get_main_menu()
            )
            bot.send_message(
                message.chat.id,
                "✅ Сообщение доставлено пользователю " + str(target_id)
            )
        except Exception as e:
            bot.send_message(
                message.chat.id,
                "❌ Не удалось отправить: " + str(e)
            )

    # ── Обработка текстовых данных модели ────

    @bot.message_handler(
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and admin_states.get(msg.from_user.id) in (
                "waiting_model_data",
            )
        )
    )
    def process_model_data(message):
        """Парсит строку: Имя | Возраст/Дата | Описание"""
        if not is_admin(message.from_user.id):
            return

        try:
            parts = [p.strip() for p in message.text.split("|")]

            if len(parts) < 3:
                bot.send_message(
                    message.chat.id,
                    "❌ Неверный формат!\n"
                    "Нужно: Имя | Дата/Возраст | Описание"
                )
                return

            name = parts[0]
            age_or_date = parts[1]
            description = parts[2]

            model_id = add_model(name, age_or_date, "", description)

            # Показываем вычисленный возраст
            model = get_model(model_id)
            age_show = model["age"] if model else "?"

            admin_states[message.from_user.id] = "waiting_preview_photo_" + str(model_id)

            bot.send_message(
                message.chat.id,
                "✅ Модель добавлена!\n\n"
                "👩 Имя: " + name + "\n"
                "🎂 Возраст: " + str(age_show) + " лет\n"
                "🆔 ID модели: " + str(model_id) + "\n\n"
                "Теперь отправь главное фото профиля (превью):"
            )

        except Exception as e:
            bot.send_message(message.chat.id, "❌ Ошибка: " + str(e))

    # ── Обработка редактирования модели ──────

    @bot.message_handler(
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and str(admin_states.get(msg.from_user.id, "")).startswith("editing_model_")
        )
    )
    def process_edit_model(message):
        """Обновляет данные модели. Точка = оставить без изменений."""
        if not is_admin(message.from_user.id):
            return

        state = admin_states.get(message.from_user.id, "")
        model_id = int(state.replace("editing_model_", ""))

        try:
            parts = [p.strip() for p in message.text.split("|")]

            if len(parts) < 3:
                bot.send_message(
                    message.chat.id,
                    "❌ Неверный формат!\n"
                    "Нужно 3 поля через |. Точка = не менять."
                )
                return

            # Точка = поле без изменений
            name = None if parts[0] == "." else parts[0]
            age_or_date = None if parts[1] == "." else parts[1]
            description = None if parts[2] == "." else parts[2]

            update_model(model_id, name, age_or_date, None, description)

            del admin_states[message.from_user.id]

            # Показываем обновлённые данные
            model = get_model(model_id)
            if model:
                bot.send_message(
                    message.chat.id,
                    "✅ Модель обновлена!\n\n"
                    "👩 Имя: " + model["name"] + "\n"
                    "🎂 Возраст: " + str(model["age"]) + " лет\n"
                    "📝 Описание: " + (model.get("description") or "нет")
                )
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Ошибка: " + str(e))

    # ── Обработка фото (превью + медиа) ──────

    @bot.message_handler(
        content_types=['photo'],
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and any(
                str(admin_states.get(msg.from_user.id, "")).startswith(p)
                for p in ["waiting_preview_photo_", "waiting_media_"]
            )
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
                "Первые 3 фото — превью для Fan.\n"
                "Все остальные — только для Premium.\n\n"
                "Когда закончишь — напиши /done"
            )

        elif state.startswith("waiting_media_"):
            model_id = int(state.replace("waiting_media_", ""))

            existing = get_all_media(model_id)
            position = len(existing) + 1
            # Первые 3 медиафайла (кроме главного) — превью
            is_preview = 1 if position <= 3 else 0

            add_model_media(model_id, file_id, 'photo', is_preview, position)

            preview_text = "👁 Fan превью" if is_preview else "🔒 Premium контент"
            bot.send_message(
                message.chat.id,
                "✅ Фото " + str(position) + " добавлено — " + preview_text + "\n"
                "Отправляй следующее или /done"
            )

    # ── Обработка видео ──────────────────────

    @bot.message_handler(
        content_types=['video'],
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and str(admin_states.get(msg.from_user.id, "")).startswith("waiting_media_")
        )
    )
    def process_model_video(message):
        if not is_admin(message.from_user.id):
            return

        state = admin_states.get(message.from_user.id, "")
        model_id = int(state.replace("waiting_media_", ""))
        file_id = message.video.file_id

        existing = get_all_media(model_id)
        position = len(existing) + 1

        # Видео всегда идёт в Premium (is_preview=0)
        add_model_media(model_id, file_id, 'video', is_preview=0, position=position)

        bot.send_message(
            message.chat.id,
            "✅ Видео " + str(position) + " добавлено — 🔒 Premium контент\n"
            "Отправляй следующее или /done"
        )

    # ── Callback — добавить модель ────────────

    @bot.callback_query_handler(func=lambda call: call.data == "admin_add_model")
    def admin_add_model_callback(call):
        if not is_admin(call.from_user.id):
            return
        bot.send_message(
            call.message.chat.id,
            "👩 Отправь данные модели:\n"
            "Имя | Дата рождения или Возраст | Описание\n\n"
            "Пример:\n"
            "Марина | 15.05.1998 | Нежная 🔥"
        )
        admin_states[call.from_user.id] = "waiting_model_data"

    # ── Callback — список моделей ─────────────

    @bot.callback_query_handler(func=lambda call: call.data == "admin_list_models")
    def admin_list_models_callback(call):
        if not is_admin(call.from_user.id):
            return

        models = get_all_models()
        if not models:
            bot.answer_callback_query(call.id, "Моделей пока нет")
            return

        lines = ["📋 Список моделей:\n"]
        for model in models:
            birth_info = ""
            if model.get("birth_date"):
                birth_info = " (ДР: " + model["birth_date"] + ")"
            lines.append(
                "👩 " + model["name"] + " | " + str(model["age"]) + " лет" + birth_info +
                " | ID: " + str(model["id"])
            )

        bot.send_message(call.message.chat.id, "\n".join(lines))

    # ── Callback — статистика ─────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
    def admin_stats_callback(call):
        if not is_admin(call.from_user.id):
            return

        from database import get_connection
        import time as _time
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as n FROM users")
        total_users = cursor.fetchone()[0]

        now_ts = int(_time.time())
        cursor.execute(
            "SELECT COUNT(*) as n FROM users WHERE subscription_type IS NOT NULL "
            "AND subscription_expires > %s", (now_ts,)
        )
        active_subs = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) as n FROM users WHERE subscription_type = 'fan_30'")
        fan_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) as n FROM users WHERE subscription_type = 'premium_90'")
        premium_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) as n FROM payments WHERE status = 'confirmed'")
        payments_confirmed = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) as s FROM payments WHERE status = 'confirmed'"
        )
        total_usd = round(cursor.fetchone()[0], 2)

        cursor.execute("SELECT COUNT(*) as n FROM models WHERE is_active = 1")
        models_count = cursor.fetchone()[0]

        conn.close()

        bot.send_message(
            call.message.chat.id,
            "📊 Статистика Miss Moldova\n\n"
            "👥 Всего пользователей: " + str(total_users) + "\n"
            "💎 Активных подписок: " + str(active_subs) + "\n"
            "  🌸 Fan: " + str(fan_count) + "\n"
            "  👑 Premium: " + str(premium_count) + "\n\n"
            "💰 Платежей подтверждено: " + str(payments_confirmed) + "\n"
            "💵 Выручка: $" + str(total_usd) + "\n\n"
            "👩 Активных моделей: " + str(models_count)
        )
