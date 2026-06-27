# handlers/admin.py
# Админ панель — добавление моделей, управление контентом, отзывами, каналами

import threading
import time

from telebot import types
from config import ADMIN_IDS, LTC_ADDRESS
from database import (
    get_all_user_ids, ban_user, unban_user, is_banned,
    get_user_by_username, get_user, get_connection, add_usd_balance,
)
from database.reviews import add_review, get_reviews, delete_review
from database.settings import get_setting, set_setting
from database.schedule import (
    add_schedule, get_all_schedules, delete_schedule, format_schedule_list
)
from utils.notify import notify_channel
from database.models import (
    add_model,
    update_model,
    get_all_models,
    get_model,
    add_model_media,
    set_preview_photo,
    set_preview_photo_2,
    deactivate_model,
    get_preview_media,
    get_all_media,
    calculate_age,
    link_model_telegram,
)
from database.withdrawals import (
    get_pending_withdrawals,
    get_withdrawal,
    process_withdrawal,
)

# Состояния админа: user_id → строка состояния
admin_states = {}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def register_admin_handlers(bot):

    # ── Отзывы ───────────────────────────────

    @bot.message_handler(commands=['addreview'])
    def add_review_command(message):
        if not is_admin(message.from_user.id):
            return
        admin_states[message.from_user.id] = "waiting_review_photo"
        bot.send_message(
            message.chat.id,
            "⭐ Отправь фото отзыва.\n\n"
            "Можешь добавить подпись к фото — она будет показана под ним.\n\n"
            "/cancel — отменить"
        )

    @bot.message_handler(commands=['delreview'])
    def del_review_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            reviews = get_reviews()
            if not reviews:
                bot.send_message(message.chat.id, "Отзывов пока нет")
                return
            lines = ["📋 Отзывы:"]
            for r in reviews:
                lines.append("ID " + str(r["id"]) + " — " + (r.get("caption") or "без подписи"))
            bot.send_message(message.chat.id, "\n".join(lines) + "\n\nУдалить: /delreview ID")
            return
        delete_review(int(parts[1]))
        bot.send_message(message.chat.id, "✅ Отзыв удалён")

    @bot.message_handler(
        content_types=['photo'],
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and admin_states.get(msg.from_user.id) == "waiting_review_photo"
        )
    )
    def process_review_photo(message):
        file_id   = message.photo[-1].file_id
        caption   = message.caption or None
        review_id = add_review(file_id, caption)
        del admin_states[message.from_user.id]
        bot.send_message(
            message.chat.id,
            "✅ Отзыв добавлен! ID: " + str(review_id) + "\n\n"
            "Для удаления: /delreview " + str(review_id)
        )

    # ── Фото приветствия ─────────────────────

    @bot.message_handler(commands=['setwelcomephoto'])
    def set_welcome_photo_command(message):
        if not is_admin(message.from_user.id):
            return
        admin_states[message.from_user.id] = "waiting_welcome_photo"
        current = get_setting("welcome_photo")
        status  = "✅ Установлено" if current else "❌ Не установлено"
        bot.send_message(
            message.chat.id,
            "🖼 Фото приветствия (/start)\n\n"
            "Статус: " + status + "\n\n"
            "Отправь новое фото — оно встанет на место.\n"
            "/delwelcomephoto — убрать фото"
        )

    @bot.message_handler(commands=['delwelcomephoto'])
    def del_welcome_photo_command(message):
        if not is_admin(message.from_user.id):
            return
        set_setting("welcome_photo", "")
        bot.send_message(message.chat.id, "✅ Фото приветствия удалено.")

    @bot.message_handler(
        content_types=['photo'],
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and admin_states.get(msg.from_user.id) == "waiting_welcome_photo"
        )
    )
    def process_welcome_photo(message):
        file_id = message.photo[-1].file_id
        set_setting("welcome_photo", file_id)
        del admin_states[message.from_user.id]
        bot.send_message(
            message.chat.id,
            "✅ Фото приветствия сохранено!\n\n"
            "Теперь при /start пользователи видят это фото.\n"
            "Проверь — напиши /start"
        )

    # ── Каналы ───────────────────────────────

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

    # ── Кошелёк ──────────────────────────────

    @bot.message_handler(commands=['wallet'])
    def wallet_command(message):
        if not is_admin(message.from_user.id):
            return
        from config import MEDIA_CHANNEL_ID, ADMIN_CHANNEL_ID
        addr = LTC_ADDRESS or "❌ НЕ ЗАДАН"
        bot.send_message(
            message.chat.id,
            "💳 LTC адрес: " + str(addr) + "\n\n"
            "📡 Медиа канал ID: " + str(MEDIA_CHANNEL_ID) + "\n"
            "🔒 Админ канал ID: " + str(ADMIN_CHANNEL_ID)
        )

    # ── Канал уведомлений ────────────────────

    @bot.message_handler(commands=['setchannel'])
    def set_channel_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2:
            from utils.notify import get_channel_id
            current = get_channel_id()
            bot.send_message(
                message.chat.id,
                "📡 Канал уведомлений\n\n"
                "Текущий ID: " + str(current or "не задан") + "\n\n"
                "Укажи ID канала:\n"
                "/setchannel -1001234567890\n\n"
                "Бот должен быть администратором канала!"
            )
            return
        channel_id = parts[1].strip()
        if not channel_id.lstrip('-').isdigit():
            bot.send_message(message.chat.id, "❌ ID должен быть числом, например: -1001234567890")
            return
        from database.settings import set_setting
        set_setting("admin_channel_id", channel_id)
        try:
            bot.send_message(int(channel_id), "✅ Канал уведомлений подключён к Miss Moldova!")
            bot.send_message(message.chat.id, "✅ Канал сохранён: " + channel_id + "\nТестовое сообщение отправлено.")
        except Exception as e:
            bot.send_message(message.chat.id, "⚠️ ID сохранён, но тест не прошёл: " + str(e) + "\nПроверь, что бот — администратор канала.")

    @bot.message_handler(commands=['testnotify'])
    def test_notify_command(message):
        if not is_admin(message.from_user.id):
            return
        from utils.notify import notify_channel, get_channel_id
        channel_id = get_channel_id()
        bot.send_message(message.chat.id, "📡 Канал: " + str(channel_id or "не задан"))
        if not channel_id:
            bot.send_message(message.chat.id, "❌ Канал не задан. Используй /setchannel <id>")
            return
        notify_channel(bot, "🔔 Тест уведомлений Miss Moldova — работает!")
        bot.send_message(message.chat.id, "✅ Отправлено в канал " + str(channel_id))

    # ── VIP: ссылка-приглашение ───────────────

    @bot.message_handler(commands=['setviplink'])
    def set_vip_link_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].startswith("http"):
            current = get_setting("vip_invite_link") or "не задана"
            bot.send_message(
                message.chat.id,
                "🔗 VIP ссылка-приглашение\n\n"
                "Текущая: " + current + "\n\n"
                "Укажи ссылку:\n"
                "/setviplink https://t.me/+xxxxxx"
            )
            return
        set_setting("vip_invite_link", parts[1].strip())
        bot.send_message(message.chat.id, "✅ VIP ссылка сохранена:\n" + parts[1].strip())

    # ── Расписание VIP-сессий ─────────────────

    @bot.message_handler(commands=['schedule'])
    def schedule_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(
                message.chat.id,
                "📅 Добавить расписание сессии:\n\n"
                "/schedule Имя ДНИ ВРЕМЯ\n\n"
                "Пример:\n"
                "/schedule Анастасия ПН,СР,ПТ 20:00\n"
                "/schedule Марина СБ,ВС 19:00\n\n"
                "Дни: ПН ВТ СР ЧТ ПТ СБ ВС"
            )
            return
        tokens = parts[1].rsplit(maxsplit=2)
        if len(tokens) < 3:
            bot.send_message(message.chat.id, "❌ Формат: /schedule Имя ДНИ ВРЕМЯ\nПример: /schedule Анастасия ПН,СР 20:00")
            return
        model_name   = tokens[0].strip()
        days         = tokens[1].strip()
        session_time = tokens[2].strip()
        if ":" not in session_time:
            bot.send_message(message.chat.id, "❌ Время должно быть в формате ЧЧ:ММ (например 20:00)")
            return
        schedule_id = add_schedule(model_name, days, session_time)
        bot.send_message(
            message.chat.id,
            "✅ Расписание добавлено!\n\n"
            "💃 " + model_name + "\n"
            "📆 " + days.upper() + "  ⏰ " + session_time + "\n"
            "🆔 ID: " + str(schedule_id) + "\n\n"
            "Бот пришлёт анонс в VIP-канал за 1 час до сессии."
        )

    @bot.message_handler(commands=['schedules'])
    def schedules_list_command(message):
        if not is_admin(message.from_user.id):
            return
        schedules = get_all_schedules()
        if not schedules:
            bot.send_message(message.chat.id, "📅 Расписаний пока нет\n\nДобавь: /schedule Имя ДНИ ВРЕМЯ")
            return
        lines = ["📅 Расписание сессий:\n"]
        for s in schedules:
            lines.append(
                "ID " + str(s["id"]) + " | 💃 " + s["model_name"] +
                " | " + s["days"] + " " + s["session_time"]
            )
        lines.append("\nУдалить: /delschedule ID")
        bot.send_message(message.chat.id, "\n".join(lines))

    @bot.message_handler(commands=['delschedule'])
    def del_schedule_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /delschedule 3")
            return
        delete_schedule(int(parts[1]))
        bot.send_message(message.chat.id, "✅ Расписание ID " + parts[1] + " удалено")

    # ── Активация подписки вручную ────────────

    @bot.message_handler(commands=['activate'])
    def activate_command(message):
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
        plan      = parts[2].lower()

        PLANS = {
            "fan_30":     {"name": "🌸 Fan",    "days": 30, "minutes": 0, "crystals": 250},
            "premium_90": {"name": "👑 Premium", "days": 90, "minutes": 0, "crystals": 600},
            "test_2min":  {"name": "🧪 Test",   "days": 0,  "minutes": 2, "crystals": 10},
        }

        if plan not in PLANS:
            bot.send_message(message.chat.id, "❌ Неизвестный план: " + plan)
            return

        p = PLANS[plan]
        from database import register_user, activate_subscription
        register_user(target_id, "", "User")
        activate_subscription(target_id, plan, p["days"], p["crystals"], minutes=p["minutes"])

        duration = str(p["minutes"]) + " минуты" if p["minutes"] > 0 else str(p["days"]) + " дней"

        bot.send_message(
            message.chat.id,
            "✅ Подписка активирована!\n\n"
            "👤 User ID: " + str(target_id) + "\n"
            "💳 План: " + p["name"] + "\n"
            "⏰ Срок: " + duration + "\n"
            "💎 Кристаллов: " + str(p["crystals"])
        )

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

        notify_channel(
            bot,
            "👑 Подписка активирована вручную\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 User: " + str(target_id) + "\n"
            "💳 План: " + p["name"] + "\n"
            "⏰ Срок: " + duration + "\n"
            "👮 Активировал: " + str(message.from_user.id)
        )

        if p["minutes"] > 0:
            def _expire():
                time.sleep(p["minutes"] * 60)
                from database import check_subscription
                if not check_subscription(target_id)["active"]:
                    try:
                        from keyboards.inline import get_subscription_menu
                        bot.send_message(
                            target_id,
                            "⏰ Тестовая подписка истекла!\n\nПолный цикл работает корректно ✅",
                            reply_markup=get_subscription_menu()
                        )
                    except Exception as e:
                        print("[ACTIVATE EXPIRY] " + str(e))
            threading.Thread(target=_expire, daemon=True).start()

    # ── Главная панель ───────────────────────

    @bot.message_handler(commands=['admin'])
    def admin_panel(message):
        if not is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "❌ Нет доступа")
            return

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("👩 Добавить модель",  callback_data="admin_add_model"),
            types.InlineKeyboardButton("📋 Список моделей",   callback_data="admin_list_models"),
            types.InlineKeyboardButton("📊 Статистика",       callback_data="admin_stats")
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
            "Дата рождения — возраст обновляется автоматически!"
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
            birth_info = (" (ДР: " + model["birth_date"] + ")") if model.get("birth_date") else ""
            tg_uid = model.get("telegram_user_id")
            link_status = ("🔗 " + str(tg_uid)) if tg_uid else "⚠️ не привязана"
            lines.append(
                "👩 " + model["name"] + " | " + str(model["age"]) + " лет" + birth_info + "\n"
                "ID: " + str(model["id"]) + " | TG: " + link_status
            )
        lines.append("\nПривязать: /linkmodel MODEL_ID TG_USER_ID")
        bot.send_message(message.chat.id, "\n\n".join(lines))

    # ── Привязать модель к Telegram аккаунту ─

    @bot.message_handler(commands=['linkmodel'])
    def link_model_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
            bot.send_message(
                message.chat.id,
                "🔗 Привязать профиль модели к Telegram аккаунту:\n\n"
                "/linkmodel MODEL_ID TELEGRAM_USER_ID\n\n"
                "Пример: /linkmodel 2 123456789\n\n"
                "MODEL_ID — из /models\n"
                "TELEGRAM_USER_ID — Telegram ID аккаунта модели\n\n"
                "Эффект:\n"
                "• Профиль каталога связывается с аккаунтом\n"
                "• Роль пользователя становится 'model'\n"
                "• Фанаты смогут открыть чат с этой моделью"
            )
            return
        model_id = int(parts[1])
        tg_uid   = int(parts[2])
        model = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель #" + str(model_id) + " не найдена")
            return
        user = get_user(tg_uid)
        if not user:
            bot.send_message(
                message.chat.id,
                "❌ Пользователь " + str(tg_uid) + " не найден.\n"
                "Модель должна сначала написать /start боту."
            )
            return
        link_model_telegram(model_id, tg_uid)
        _set_user_role(tg_uid, "model")
        bot.send_message(
            message.chat.id,
            "✅ Профиль «" + model["name"] + "» (#" + str(model_id) + ") "
            "связан с пользователем " + str(tg_uid) + "\n\n"
            "Теперь фанаты могут открыть чат с этой моделью."
        )
        try:
            bot.send_message(
                tg_uid,
                "✅ Твой профиль «" + model["name"] + "» активирован!\n\n"
                "Когда фанат купит 24-часовой чат — ты получишь уведомление и сможешь писать прямо сюда.\n\n"
                "Команды:\n"
                "/balance — твой баланс\n"
                "/earnings — статистика\n"
                "/withdraw — вывод средств"
            )
        except Exception as e:
            print("[LINKMODEL] Уведомление модели не доставлено: " + str(e))
        notify_channel(
            bot,
            "🔗 Модель привязана к аккаунту\n"
            "━━━━━━━━━━━━━━━\n"
            "👩 Профиль: " + model["name"] + " (#" + str(model_id) + ")\n"
            "🆔 TG User: " + str(tg_uid) + "\n"
            "👮 Привязал: " + str(message.from_user.id)
        )

    # ── Заявки на вывод средств ───────────────

    @bot.message_handler(commands=['withdrawals'])
    def withdrawals_command(message):
        if not is_admin(message.from_user.id):
            return
        pending = get_pending_withdrawals()
        if not pending:
            bot.send_message(message.chat.id, "✅ Нет pending заявок на вывод")
            return
        lines = ["💸 Заявки на вывод (pending: " + str(len(pending)) + "):\n"]
        for w in pending:
            lines.append(
                "━━━━━━━━━━━━━━━\n"
                "🆔 Заявка #" + str(w["id"]) + "\n"
                "👤 Модель: " + str(w["model_user_id"]) + "\n"
                "💵 Сумма: $" + str(round(w["amount_usd"], 2)) + "\n"
                "📬 LTC: " + w["ltc_address"] + "\n\n"
                "/approve " + str(w["id"]) + " — одобрить\n"
                "/reject " + str(w["id"]) + " причина — отклонить"
            )
        bot.send_message(message.chat.id, "\n".join(lines))

    @bot.message_handler(commands=['approve'])
    def approve_withdrawal_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Использование: /approve ID [примечание]")
            return
        req_id = int(parts[1])
        notes  = parts[2].strip() if len(parts) > 2 else ""
        req = get_withdrawal(req_id)
        if not req:
            bot.send_message(message.chat.id, "❌ Заявка #" + str(req_id) + " не найдена")
            return
        if req["status"] != "pending":
            bot.send_message(
                message.chat.id,
                "⚠️ Заявка #" + str(req_id) + " уже обработана (статус: " + req["status"] + ")"
            )
            return
        result = process_withdrawal(req_id, "paid", notes)
        if not result:
            bot.send_message(message.chat.id, "❌ Ошибка обработки заявки")
            return
        bot.send_message(
            message.chat.id,
            "✅ Заявка #" + str(req_id) + " одобрена!\n\n"
            "👤 Модель: " + str(req["model_user_id"]) + "\n"
            "💵 Сумма: $" + str(round(req["amount_usd"], 2)) + "\n"
            "📬 LTC: " + req["ltc_address"] + "\n\n"
            "Баланс модели списан. Уведомление отправлено."
        )
        try:
            bot.send_message(
                req["model_user_id"],
                "✅ Выплата одобрена!\n\n"
                "💵 Сумма: $" + str(round(req["amount_usd"], 2)) + "\n"
                "📬 Адрес: " + req["ltc_address"] + "\n\n"
                "LTC отправлен на ваш кошелёк." +
                ("\n\nПримечание: " + notes if notes else "")
            )
        except Exception as e:
            print("[APPROVE] Уведомление модели не доставлено: " + str(e))

    @bot.message_handler(commands=['reject'])
    def reject_withdrawal_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Использование: /reject ID причина")
            return
        req_id = int(parts[1])
        reason = parts[2].strip()
        req = get_withdrawal(req_id)
        if not req:
            bot.send_message(message.chat.id, "❌ Заявка #" + str(req_id) + " не найдена")
            return
        if req["status"] != "pending":
            bot.send_message(
                message.chat.id,
                "⚠️ Заявка #" + str(req_id) + " уже обработана (статус: " + req["status"] + ")"
            )
            return
        process_withdrawal(req_id, "rejected", reason)
        bot.send_message(
            message.chat.id,
            "❌ Заявка #" + str(req_id) + " отклонена.\n\n"
            "👤 Модель: " + str(req["model_user_id"]) + "\n"
            "💵 Сумма: $" + str(round(req["amount_usd"], 2)) + "\n"
            "📝 Причина: " + reason + "\n\n"
            "Баланс модели НЕ списан."
        )
        try:
            bot.send_message(
                req["model_user_id"],
                "❌ Заявка на вывод #" + str(req_id) + " отклонена.\n\n"
                "💵 Сумма: $" + str(round(req["amount_usd"], 2)) + "\n"
                "📝 Причина: " + reason + "\n\n"
                "Твой баланс не изменился. При вопросах обратись к администратору."
            )
        except Exception as e:
            print("[REJECT] Уведомление модели не доставлено: " + str(e))

    # ── Редактировать модель ─────────────────

    @bot.message_handler(commands=['editmodel'])
    def edit_model_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID модели\n\nПример: /editmodel 3")
            return
        model_id = int(parts[1])
        model    = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель с ID " + str(model_id) + " не найдена")
            return
        admin_states[message.from_user.id] = "editing_model_" + str(model_id)
        bot.send_message(
            message.chat.id,
            "✏️ Редактирование: " + model["name"] + " (ID " + str(model_id) + ")\n\n"
            "Текущие данные:\n"
            "Имя: " + model["name"] + "\n"
            "Возраст: " + str(model.get("age", "?")) + " лет\n"
            "Дата рождения: " + str(model.get("birth_date", "не задана")) + "\n"
            "Описание: " + (model.get("description") or "нет") + "\n\n"
            "Отправь новые данные в формате:\n"
            "Имя | Дата/Возраст | Описание\n\n"
            "Точка = оставить без изменений:\n"
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
        model    = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель не найдена")
            return
        deactivate_model(model_id)
        bot.send_message(
            message.chat.id,
            "✅ Модель " + model["name"] + " (ID " + str(model_id) + ") деактивирована."
        )

    # ── Заменить главное фото модели ─────────

    @bot.message_handler(commands=['setphoto'])
    def set_photo_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /setphoto 3")
            return
        model_id = int(parts[1])
        model    = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель не найдена")
            return
        admin_states[message.from_user.id] = "waiting_preview_photo_" + str(model_id)
        bot.send_message(message.chat.id, "📸 Отправь аватарку 1 для " + model["name"] + ":")

    @bot.message_handler(commands=['setphoto2'])
    def set_photo2_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /setphoto2 3")
            return
        model_id = int(parts[1])
        model    = get_model(model_id)
        if not model:
            bot.send_message(message.chat.id, "❌ Модель не найдена")
            return
        admin_states[message.from_user.id] = "waiting_preview_photo2_" + str(model_id)
        bot.send_message(message.chat.id, "📸 Отправь аватарку 2 для " + model["name"] + ":")

    # ── Добавить медиа к модели ───────────────

    @bot.message_handler(commands=['addmedia'])
    def add_media_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Укажи ID: /addmedia 3")
            return
        model_id  = int(parts[1])
        model     = get_model(model_id)
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
        model_id     = int(state.replace("waiting_media_", ""))
        model        = get_model(model_id)
        if not model:
            return
        all_media    = get_all_media(model_id)
        preview_media = get_preview_media(model_id)
        del admin_states[message.from_user.id]
        bot.send_message(
            message.chat.id,
            "🎉 Загрузка завершена!\n\n"
            "👩 Имя: " + model["name"] + "\n"
            "🎂 Возраст: " + str(model["age"]) + " лет\n\n"
            "📸 Всего медиа: " + str(len(all_media)) + "\n"
            "👁 Превью Fan: " + str(len(preview_media)) + " фото\n"
            "🔒 Premium: " + str(len(all_media) - len(preview_media)) + " файлов"
        )

    # ── Бан / разбан пользователей ──────────

    @bot.message_handler(commands=['ban'])
    def ban_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id,
                "🚫 Заблокировать пользователя:\n\n"
                "/ban USER_ID\n"
                "/ban @username\n\n"
                "Примеры:\n"
                "/ban 123456789\n"
                "/ban @ivan_petrov")
            return

        arg = parts[1]
        if arg.startswith("@") or (not arg.isdigit()):
            user = get_user_by_username(arg)
            if not user:
                bot.send_message(message.chat.id,
                    "❌ Пользователь @" + arg.lstrip("@") + " не найден в боте.\n\n"
                    "Он должен был хотя бы раз запустить бота.")
                return
            target_id = user["user_id"]
            display = "@" + (user.get("username") or str(target_id))
        else:
            target_id = int(arg)
            display = "ID " + str(target_id)

        if target_id == message.from_user.id:
            bot.send_message(message.chat.id, "❌ Нельзя забанить себя")
            return

        ban_user(target_id)
        bot.send_message(message.chat.id,
            "🚫 " + display + " заблокирован.\n"
            "Разблокировать: /unban " + str(target_id))
        try:
            bot.send_message(target_id,
                "🚫 Ваш аккаунт заблокирован.\n"
                "По вопросам обращайтесь к администратору.")
        except Exception:
            pass
        notify_channel(bot,
            "🚫 Пользователь заблокирован\n"
            "👤 " + display + " (ID: " + str(target_id) + ")\n"
            "👮 Админ: " + str(message.from_user.id))

    @bot.message_handler(commands=['unban'])
    def unban_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(message.chat.id,
                "✅ Разблокировать: /unban USER_ID или /unban @username")
            return

        arg = parts[1]
        if arg.startswith("@") or (not arg.isdigit()):
            user = get_user_by_username(arg)
            if not user:
                bot.send_message(message.chat.id,
                    "❌ Пользователь @" + arg.lstrip("@") + " не найден.")
                return
            target_id = user["user_id"]
            display = "@" + (user.get("username") or str(target_id))
        else:
            target_id = int(arg)
            display = "ID " + str(target_id)

        unban_user(target_id)
        bot.send_message(message.chat.id,
            "✅ " + display + " разблокирован.")
        try:
            bot.send_message(target_id,
                "✅ Ваш аккаунт разблокирован. Добро пожаловать обратно!")
        except Exception:
            pass

    # ── Рассылка всем пользователям ─────────

    @bot.message_handler(commands=['broadcast'])
    def broadcast_command(message):
        if not is_admin(message.from_user.id):
            return
        admin_states[message.from_user.id] = "waiting_broadcast"
        bot.send_message(
            message.chat.id,
            "📢 Рассылка\n\n"
            "Отправь сообщение для рассылки:\n"
            "• Просто текст\n"
            "• Фото с подписью\n\n"
            "/cancel — отменить"
        )

    @bot.message_handler(
        content_types=['text'],
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and admin_states.get(msg.from_user.id) == "waiting_broadcast"
            and not msg.text.startswith('/')
        )
    )
    def process_broadcast_text(message):
        if admin_states.get(message.from_user.id) != "waiting_broadcast":
            return
        del admin_states[message.from_user.id]
        user_ids = get_all_user_ids()
        text = message.text
        bot.send_message(message.chat.id, "⏳ Рассылка начата... 0/" + str(len(user_ids)))

        def _send():
            ok = 0
            fail = 0
            for uid in user_ids:
                try:
                    bot.send_message(uid, text)
                    ok += 1
                    time.sleep(0.05)
                except Exception:
                    fail += 1
            bot.send_message(
                message.chat.id,
                "✅ Рассылка завершена!\n\n"
                "✔️ Доставлено: " + str(ok) + "\n"
                "❌ Ошибок: " + str(fail)
            )
        threading.Thread(target=_send, daemon=True).start()

    @bot.message_handler(
        content_types=['photo'],
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and admin_states.get(msg.from_user.id) == "waiting_broadcast"
        )
    )
    def process_broadcast_photo(message):
        if admin_states.get(message.from_user.id) != "waiting_broadcast":
            return
        del admin_states[message.from_user.id]
        user_ids = get_all_user_ids()
        file_id  = message.photo[-1].file_id
        caption  = message.caption or ""
        bot.send_message(message.chat.id, "⏳ Рассылка начата... 0/" + str(len(user_ids)))

        def _send():
            ok = 0
            fail = 0
            for uid in user_ids:
                try:
                    bot.send_photo(uid, file_id, caption=caption)
                    ok += 1
                    time.sleep(0.05)
                except Exception:
                    fail += 1
            bot.send_message(
                message.chat.id,
                "✅ Рассылка завершена!\n\n"
                "✔️ Доставлено: " + str(ok) + "\n"
                "❌ Ошибок: " + str(fail)
            )
        threading.Thread(target=_send, daemon=True).start()

    # ── Отмена текущей операции ──────────────

    @bot.message_handler(commands=['cancel'])
    def cancel_command(message):
        if not is_admin(message.from_user.id):
            return
        state = admin_states.pop(message.from_user.id, "")
        if state:
            bot.send_message(message.chat.id, "❌ Операция отменена")
        else:
            bot.send_message(message.chat.id, "Нет активной операции")

    # ── Управление ролями ─────────────────────

    def _set_user_role(user_id: int, role: str):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET user_role = %s WHERE user_id = %s",
            (role, user_id)
        )
        conn.commit()
        conn.close()

    @bot.message_handler(commands=['setmodel'])
    def set_model_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(
                message.chat.id,
                "👩 Назначить модель:\n\n"
                "/setmodel USER_ID\n\n"
                "Пользователь должен был хотя бы раз запустить бота.\n"
                "Отменить: /setfan USER_ID"
            )
            return
        target_id = int(parts[1])
        user = get_user(target_id)
        if not user:
            bot.send_message(
                message.chat.id,
                "❌ Пользователь " + str(target_id) + " не найден.\n"
                "Он должен запустить бота командой /start."
            )
            return
        _set_user_role(target_id, "model")
        bot.send_message(
            message.chat.id,
            "✅ Пользователь " + str(target_id) + " назначен моделью.\n\n"
            "👩 Роль: model\n"
            "Теперь все её сообщения бот проверяет антифродом и пересылает фанатам.\n\n"
            "Отменить: /setfan " + str(target_id)
        )
        notify_channel(
            bot,
            "👩 Новая модель зарегистрирована\n"
            "━━━━━━━━━━━━━━━\n"
            "🆔 User ID: " + str(target_id) + "\n"
            "👮 Назначил: " + str(message.from_user.id)
        )
        try:
            bot.send_message(
                target_id,
                "✅ Твой аккаунт активирован как модель!\n\n"
                "Когда фанат купит 24-часовой чат — ты получишь уведомление.\n"
                "Пиши мне прямо сюда, я пересылаю сообщения фанатам.\n\n"
                "❗ Запрещено: делиться контактами, ссылками, номерами телефона.\n"
                "Нарушение = автоматический бан."
            )
        except Exception as e:
            print("[SETMODEL] Уведомление модели не доставлено: " + str(e))

    @bot.message_handler(commands=['setfan'])
    def set_fan_command(message):
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            bot.send_message(message.chat.id, "❌ Использование: /setfan USER_ID")
            return
        target_id = int(parts[1])
        _set_user_role(target_id, "fan")
        bot.send_message(
            message.chat.id,
            "✅ Пользователь " + str(target_id) + " переведён в роль fan."
        )

    @bot.message_handler(commands=['topup'])
    def topup_command(message):
        """Admin manually tops up a user's USD balance."""
        if not is_admin(message.from_user.id):
            return
        parts = message.text.split()
        if len(parts) < 3 or not parts[1].isdigit():
            bot.send_message(
                message.chat.id,
                "💵 Пополнить баланс:\n\n"
                "/topup USER_ID СУММА\n\n"
                "Пример: /topup 123456789 10.00"
            )
            return
        target_id = int(parts[1])
        try:
            amount = float(parts[2])
        except ValueError:
            bot.send_message(message.chat.id, "❌ Некорректная сумма")
            return
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Сумма должна быть > 0")
            return
        user = get_user(target_id)
        if not user:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
            return
        add_usd_balance(target_id, amount, "Пополнение администратором")
        bot.send_message(
            message.chat.id,
            "✅ Баланс пополнен!\n\n"
            "👤 User: " + str(target_id) + "\n"
            "💵 Сумма: +$" + str(round(amount, 2)) + "\n"
            "👮 Добавил: " + str(message.from_user.id)
        )
        try:
            bot.send_message(
                target_id,
                "💵 Ваш баланс пополнен: +$" + str(round(amount, 2))
            )
        except Exception:
            pass

    # ── Ответ пользователю через бота ────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("admin_reply_"))
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

    @bot.message_handler(
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and str(admin_states.get(msg.from_user.id, "")).startswith("replying_to_")
        )
    )
    def send_reply_to_user(message):
        state     = admin_states.pop(message.from_user.id, "")
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
            bot.send_message(message.chat.id, "✅ Сообщение доставлено пользователю " + str(target_id))
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Не удалось отправить: " + str(e))

    # ── Обработка текста модели ───────────────

    @bot.message_handler(
        func=lambda msg: (
            is_admin(msg.from_user.id)
            and admin_states.get(msg.from_user.id) == "waiting_model_data"
        )
    )
    def process_model_data(message):
        try:
            parts = [p.strip() for p in message.text.split("|")]
            if len(parts) < 3:
                bot.send_message(
                    message.chat.id,
                    "❌ Неверный формат!\n"
                    "Нужно: Имя | Дата/Возраст | Описание"
                )
                return

            name        = parts[0]
            age_or_date = parts[1]
            description = parts[2]

            model_id  = add_model(name, age_or_date, "", description)
            model     = get_model(model_id)
            age_show  = model["age"] if model else "?"

            admin_states[message.from_user.id] = "waiting_preview_photo_" + str(model_id)

            bot.send_message(
                message.chat.id,
                "✅ Модель добавлена!\n\n"
                "👩 Имя: " + name + "\n"
                "🎂 Возраст: " + str(age_show) + " лет\n"
                "🆔 ID модели: " + str(model_id) + "\n\n"
                "Теперь отправь аватарку 1 (главное фото профиля):"
            )

            notify_channel(
                bot,
                "👩 Новая модель добавлена!\n"
                "━━━━━━━━━━━━━━━\n"
                "Имя: " + name + "\n"
                "Возраст: " + str(age_show) + " лет\n"
                "ID: " + str(model_id)
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
        state    = admin_states.get(message.from_user.id, "")
        model_id = int(state.replace("editing_model_", ""))
        try:
            parts = [p.strip() for p in message.text.split("|")]
            if len(parts) < 3:
                bot.send_message(message.chat.id, "❌ Нужно 3 поля через |. Точка = не менять.")
                return
            name        = None if parts[0] == "." else parts[0]
            age_or_date = None if parts[1] == "." else parts[1]
            description = None if parts[2] == "." else parts[2]
            update_model(model_id, name, age_or_date, None, description)
            del admin_states[message.from_user.id]
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
                for p in ["waiting_preview_photo_", "waiting_preview_photo2_", "waiting_media_"]
            )
        )
    )
    def process_model_photo(message):
        state   = admin_states.get(message.from_user.id, "")
        file_id = message.photo[-1].file_id

        if state.startswith("waiting_preview_photo2_"):
            model_id = int(state.replace("waiting_preview_photo2_", ""))
            set_preview_photo_2(model_id, file_id)
            admin_states[message.from_user.id] = "waiting_media_" + str(model_id)
            bot.send_message(
                message.chat.id,
                "✅ Аватарка 2 сохранена!\n\n"
                "Теперь отправляй фото/видео для контента.\n"
                "Первые 3 фото — превью для Fan.\n"
                "Все остальные — только для Premium.\n\n"
                "Когда закончишь — напиши /done"
            )

        elif state.startswith("waiting_preview_photo_"):
            model_id = int(state.replace("waiting_preview_photo_", ""))
            set_preview_photo(model_id, file_id)
            add_model_media(model_id, file_id, 'photo', is_preview=1, position=1)
            admin_states[message.from_user.id] = "waiting_preview_photo2_" + str(model_id)
            bot.send_message(
                message.chat.id,
                "✅ Аватарка 1 сохранена!\n\n"
                "Теперь отправь аватарку 2 👇\n"
                "(второе фото которое будет показано в профиле)"
            )

        elif state.startswith("waiting_media_"):
            model_id = int(state.replace("waiting_media_", ""))
            existing  = get_all_media(model_id)
            position  = len(existing) + 1
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
        state    = admin_states.get(message.from_user.id, "")
        model_id = int(state.replace("waiting_media_", ""))
        file_id  = message.video.file_id
        existing = get_all_media(model_id)
        position = len(existing) + 1
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
            birth_info = (" (ДР: " + model["birth_date"] + ")") if model.get("birth_date") else ""
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

        import time as _time
        from database import get_connection
        conn   = get_connection()
        cursor = conn.cursor()
        now_ts = int(_time.time())

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_type IS NOT NULL "
            "AND subscription_expires > %s", (now_ts,)
        )
        active_subs = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_type = 'fan_30' "
            "AND subscription_expires > %s", (now_ts,)
        )
        fan_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE subscription_type = 'premium_90' "
            "AND subscription_expires > %s", (now_ts,)
        )
        premium_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'confirmed'")
        payments_confirmed = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM payments WHERE status = 'confirmed'"
        )
        total_usd = round(cursor.fetchone()[0], 2)

        cursor.execute("SELECT COUNT(*) FROM models WHERE is_active = 1")
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
