# handlers/callback.py
# Все inline-callback хендлеры бота
# Изменено:
# 1. monitor_payment передаёт minutes= в activate_subscription
# 2. asyncio убран — check_payment синхронная
# 3. crystal_history с кнопкой Назад

import time
import threading

from keyboards.inline import (
    get_main_menu,
    get_subscription_menu,
    get_crystal_packs_menu,
    get_payment_keyboard,
    get_profile_menu,
    get_payment_method_keyboard,
    get_exchange_card_keyboard,
    get_exchange_contact_keyboard,
    LEI_RATE,
    EXCHANGE_ADMIN
)
from utils.payments import (
    generate_payment_invoice,
    generate_crystal_invoice,
    format_payment_message
)
from utils.blockchain import check_payment
from database import (
    register_user,
    get_user,
    activate_subscription,
    add_crystals,
    check_subscription,
    save_payment,
    confirm_payment,
    get_days_since_registration,
    get_connection
)
from config import LTC_ADDRESS, ADMIN_IDS
from utils.notify import notify_channel
from telebot import types

# Словарь активных платежей: user_id → invoice
active_payments = {}

# Блокировка против двойного зачисления
_activation_lock = threading.Lock()


def _get_payment_status(payment_id: str) -> str:
    """Возвращает статус платежа из БД ('pending' / 'confirmed')."""
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM payments WHERE payment_id = %s", (payment_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else "pending"
    except Exception:
        return "pending"


def _schedule_test_expiry(bot, chat_id: int, user_id: int, minutes: int):
    """Уведомляет пользователя когда тестовая подписка истекает."""
    def _notify():
        time.sleep(minutes * 60)
        from database import check_subscription
        sub = check_subscription(user_id)
        if not sub["active"]:
            try:
                bot.send_message(
                    chat_id,
                    "⏰ Тестовая подписка истекла!\n\n"
                    "Полный цикл работает корректно ✅\n\n"
                    "Готов перейти на боевую подписку?\n"
                    "Выбери тариф ниже 👇",
                    reply_markup=get_subscription_menu()
                )
            except Exception as e:
                print("[EXPIRY NOTIFY ERROR] " + str(e))

    thread = threading.Thread(target=_notify, daemon=True)
    thread.start()


# ─────────────────────────────────────────────
# Безопасное редактирование сообщения
# ─────────────────────────────────────────────

def safe_edit(bot, call, text: str, reply_markup=None, parse_mode=None):
    """
    Редактирует сообщение. Если оно с фото — удаляет и шлёт новое.
    """
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except Exception as e:
        err = str(e).lower()
        if (
            "there is no text" in err
            or "message can't be edited" in err
            or "message to edit not found" in err
            or "message is not modified" in err
        ):
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.send_message(
                chat_id=call.message.chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            print("[SAFE_EDIT ERROR] " + str(e))


# ─────────────────────────────────────────────
# Мониторинг платежа
# ─────────────────────────────────────────────

def monitor_payment(bot, chat_id: int, user_id: int, invoice: dict, one_shot: bool = False):
    """
    Фоновый поток — проверяет LTC каждые 30 секунд, максимум 60 минут.
    one_shot=True — одиночная проверка без цикла (вызывается при нажатии «Я оплатил»).
    """
    expected_amount = invoice["amount_ltc"]
    payment_id      = invoice["payment_id"]
    invoice_type    = invoice.get("type", "subscription")
    created_at      = invoice.get("created_at", int(time.time()))
    timeout         = 3600
    check_interval  = 30
    start_time      = time.time()

    print("[MONITOR] Старт мониторинга " + payment_id +
          " сумма " + str(expected_amount) + " LTC")

    while time.time() - start_time < timeout:
        try:
            payment_received, amount = check_payment(
                LTC_ADDRESS,
                expected_amount,
                created_at
            )

            if payment_received:
                with _activation_lock:
                    if _get_payment_status(payment_id) == "confirmed":
                        active_payments.pop(user_id, None)
                        return  # Уже активировано другим потоком
                    confirm_payment(payment_id)

                if invoice_type == "subscription":
                    sub_type = invoice["sub_type"]
                    days     = invoice["days"]
                    minutes  = invoice.get("minutes", 0)  # тестовая подписка
                    crystals = invoice["crystals"]
                    sub_name = invoice["sub_name"]

                    # Передаём minutes= — для теста подписка на 2 минуты
                    activate_subscription(
                        user_id, sub_type, days, crystals, minutes=minutes
                    )

                    # Формируем текст подтверждения
                    if minutes > 0:
                        duration_text = "⏱ Срок: " + str(minutes) + " минуты (тест)"
                    else:
                        duration_text = "⏰ Срок: " + str(days) + " дней"

                    bot.send_message(
                        chat_id,
                        "✅ ПЛАТЁЖ ПОДТВЕРЖДЁН!\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "🎉 Подписка " + sub_name + " активирована!\n"
                        + duration_text + "\n"
                        "💎 Начислено: " + str(crystals) + " кристаллов\n\n"
                        "Добро пожаловать в клуб! ❤️",
                        reply_markup=get_main_menu()
                    )

                    # Для тестовой подписки — уведомляем об истечении
                    if minutes > 0:
                        _schedule_test_expiry(bot, chat_id, user_id, minutes)

                else:  # crystals
                    total_crystals = invoice["total_crystals"]
                    pack_name      = invoice["pack_name"]
                    add_crystals(user_id, total_crystals, "Покупка пакета " + pack_name)

                    bot.send_message(
                        chat_id,
                        "✅ ПЛАТЁЖ ПОДТВЕРЖДЁН!\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "💎 Начислено: " + str(total_crystals) + " кристаллов\n\n"
                        "Приятного использования! ✨",
                        reply_markup=get_main_menu()
                    )

                # Уведомляем админов
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(
                            admin_id,
                            "✅ Платёж подтверждён!\n\n"
                            "👤 User: " + str(user_id) + "\n"
                            "💰 Сумма: " + str(amount) + " LTC\n"
                            "🆔 ID: " + payment_id
                        )
                    except Exception as e:
                        print("[ADMIN NOTIFY ERROR] " + str(e))

                if invoice_type == "subscription":
                    notify_channel(
                        bot,
                        "✅ Платёж подтверждён!\n"
                        "━━━━━━━━━━━━━━━\n"
                        "👤 User: " + str(user_id) + "\n"
                        "💳 Тариф: " + invoice["sub_name"] + "\n"
                        "💰 Сумма: " + str(amount) + " LTC\n"
                        "🆔 ID: " + payment_id
                    )
                else:
                    notify_channel(
                        bot,
                        "✅ Платёж кристаллов подтверждён!\n"
                        "━━━━━━━━━━━━━━━\n"
                        "👤 User: " + str(user_id) + "\n"
                        "💎 Кристаллов: " + str(invoice["total_crystals"]) + "\n"
                        "💰 Сумма: " + str(amount) + " LTC\n"
                        "🆔 ID: " + payment_id
                    )

                active_payments.pop(user_id, None)
                print("[MONITOR] Платёж " + payment_id + " подтверждён!")
                return

            if one_shot:
                return  # Одиночная проверка — выходим без ожидания
            time.sleep(check_interval)

        except Exception as e:
            print("[MONITOR ERROR] " + str(e))
            if one_shot:
                return
            time.sleep(check_interval)

    if one_shot:
        return

    # Время вышло
    bot.send_message(
        chat_id,
        "⏰ Время истекло\n\n"
        "Счёт более не действителен.\n"
        "Создай новый в меню подписок."
    )
    active_payments.pop(user_id, None)
    print("[MONITOR] Платёж " + payment_id + " истёк")


# ─────────────────────────────────────────────
# Регистрация хендлеров
# ─────────────────────────────────────────────

def register_callback_handlers(bot):

    # ── Назад в главное меню ─────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
    def back_to_main(call):
        bot.answer_callback_query(call.id)
        safe_edit(bot, call, "❤️ Главное меню", reply_markup=get_main_menu())

    # ── О системе кристаллов ─────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "about_system")
    def about_system(call):
        bot.answer_callback_query(call.id)
        text = (
            "💎 Система кристаллов Miss Moldova\n\n"
            "Кристаллы — внутренняя валюта клуба.\n"
            "Получай их с подпиской или покупай отдельно!\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💳 Подписки:\n"
            "🌸 Fan 30 дней — $25 → 250 💎\n"
            "👑 Premium 90 дней — $50 → 600 💎\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📦 Пакеты кристаллов:\n"
            "💎 50 кристаллов — $5\n"
            "💎 120 кристаллов — $10 (+20 бонус)\n"
            "💎 300 кристаллов — $25 (+50 бонус)\n"
            "💎 650 кристаллов — $50 (+150 бонус)\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🛍 На что тратить:\n"
            "💬 Написать модели — 10 💎\n"
            "❤️ Разблокировать фото — 5 💎\n"
            "🎁 Подарок модели — 20 💎\n"
            "🔓 Эксклюзивный контент — 15 💎\n"
            "👁 Просмотр без подписки — 3 💎\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💡 Кристаллы не сгорают!\n"
            "Используй их в любое время ✨"
        )
        safe_edit(bot, call, text, reply_markup=get_main_menu())

    # ── Мой профиль ──────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "my_profile")
    def my_profile(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        user     = get_user(user_id)
        sub      = check_subscription(user_id)
        days_reg = get_days_since_registration(user_id)

        if sub["active"]:
            sub_type_val = sub.get("type") or ""
            is_premium = "premium" in sub_type_val or sub_type_val == "test_2min"
            if is_premium:
                if sub["days_left"] == 0:
                    sec = sub.get("seconds_left", 0)
                    sub_text = "👑 Premium • " + str(sec) + " сек (тест)"
                else:
                    sub_text = "👑 Premium • " + str(sub["days_left"]) + " дней"
            else:
                sub_text = "🌸 Fan • " + str(sub["days_left"]) + " дней"
        else:
            sub_text = "❌ Нет подписки"

        crystals       = user.get("crystals", 0) if user else 0
        profiles_viewed = user.get("profiles_viewed", 0) if user else 0
        favorites       = user.get("favorites_count", 0) if user else 0
        gifts           = user.get("gifts_sent", 0) if user else 0

        username  = call.from_user.username
        name_text = "@" + username if username else call.from_user.full_name

        text = (
            "👤 Профиль участника\n"
            "━━━━━━━━━━━━━━━\n\n"
            "🏷 " + name_text + "\n"
            "🆔 ID: " + str(user_id) + "\n"
            "📅 В клубе: " + str(days_reg) + " дней\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💎 Баланс: " + str(crystals) + " кристаллов\n"
            "🎫 Подписка: " + sub_text + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📊 Статистика:\n"
            "👁 Просмотрено профилей: " + str(profiles_viewed) + "\n"
            "❤️ В избранном: " + str(favorites) + "\n"
            "🎁 Подарков отправлено: " + str(gifts) + "\n"
            "━━━━━━━━━━━━━━━"
        )

        has_premium = sub["active"] and ("premium" in (sub.get("type") or "") or sub.get("type") == "test_2min")
        safe_edit(bot, call, text, reply_markup=get_profile_menu(has_premium))

    # ── Меню подписок ────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "subscription")
    def subscription_menu(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        sub = check_subscription(user_id)

        if sub["active"]:
            sub_type_val = sub.get("type") or ""
            is_test = sub_type_val == "test_2min"
            is_premium = "premium" in sub_type_val or is_test
            sub_name = "👑 Premium" if is_premium else "🌸 Fan"
            if is_test:
                time_left = str(sub.get("seconds_left", 0)) + " сек (тест)"
            else:
                time_left = str(sub["days_left"]) + " дней"
            text = (
                "💎 Твоя подписка\n\n"
                "Тип: " + sub_name + "\n"
                "⏰ Осталось: " + time_left + "\n\n"
                "Хочешь продлить или сменить тариф?\n\n"
                "━━━━━━━━━━━━━━━\n"
                "🌸 Fan — 30 дней • $25 • 250 💎\n"
                "👑 Premium — 90 дней • $50 • 600 💎"
            )
        else:
            text = (
                "💎 Выбери подписку\n\n"
                "━━━━━━━━━━━━━━━\n"
                "🌸 Fan — 30 дней • $25\n"
                "• 📸 3 фото каждой модели\n"
                "• 💎 250 кристаллов\n\n"
                "━━━━━━━━━━━━━━━\n"
                "👑 Premium — 90 дней • $50\n"
                "• 📸 Все фото и видео\n"
                "• 💎 600 кристаллов\n"
                "• 🔓 Эксклюзивный контент\n"
                "━━━━━━━━━━━━━━━"
            )

        safe_edit(bot, call, text, reply_markup=get_subscription_menu())

    # ── Выбор подписки → выбор метода оплаты ────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("sub_"))
    def handle_subscription(call):
        bot.answer_callback_query(call.id)
        sub_type = call.data[4:]   # "fan_30" / "premium_90"
        plan_key = "sub_" + sub_type

        from utils.payments import SUBSCRIPTION_PRICES
        info = SUBSCRIPTION_PRICES.get(sub_type, SUBSCRIPTION_PRICES["fan_30"])
        lei  = info["usd"] * LEI_RATE

        text = (
            "💎 " + info["name"] + " — " + str(info["days"]) + " дней\n"
            "━━━━━━━━━━━━━━━\n\n"
            "💰 Стоимость: $" + str(info["usd"]) + " USD\n\n"
            "Выбери способ оплаты:\n\n"
            "🔷 Крипта (LTC) — по актуальному курсу\n"
            "💳 Обмен — " + str(lei) + " лей\n"
            "    (курс: 20 лей = 1 USDT)"
        )
        safe_edit(bot, call, text,
                  reply_markup=get_payment_method_keyboard(plan_key, "subscription"))

    # ── LTC оплата подписки ───────────────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ltc_sub_"))
    def handle_ltc_subscription(call):
        bot.answer_callback_query(call.id, "⏳ Генерируем счёт...")
        sub_type = call.data[8:]   # strip "ltc_sub_"
        user_id  = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        invoice = generate_payment_invoice(sub_type, user_id)
        save_payment(user_id, invoice["payment_id"], sub_type,
                     invoice["amount_ltc"], invoice["amount_usd"], invoice["crystals"])
        active_payments[user_id] = invoice

        safe_edit(bot, call, format_payment_message(invoice),
                  reply_markup=get_payment_keyboard(invoice["amount_ltc"], invoice["wallet"]),
                  parse_mode="Markdown")

        minutes  = invoice.get("minutes", 0)
        duration = str(minutes) + " мин (тест)" if minutes > 0 else str(invoice["days"]) + " дней"
        notify_text = (
            "🔔 Новый счёт на подписку (LTC)\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 User: " + str(user_id) + "\n"
            "💳 Тариф: " + invoice["sub_name"] + "\n"
            "⏰ Срок: " + duration + "\n"
            "💰 Сумма: " + str(invoice["amount_ltc"]) + " LTC\n"
            "🆔 ID: " + invoice["payment_id"]
        )
        for admin_id in ADMIN_IDS:
            try: bot.send_message(admin_id, notify_text)
            except Exception as e: print("[ADMIN NOTIFY] " + str(e))
        notify_channel(bot, notify_text)

        threading.Thread(target=monitor_payment,
                         args=(bot, call.message.chat.id, user_id, invoice),
                         daemon=True).start()

    # ── Обмен подписки → выбор карты ─────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("exch_sub_"))
    def handle_exchange_sub(call):
        bot.answer_callback_query(call.id)
        sub_type = call.data[9:]   # strip "exch_sub_"
        plan_key = "sub_" + sub_type

        from utils.payments import SUBSCRIPTION_PRICES
        info = SUBSCRIPTION_PRICES.get(sub_type, SUBSCRIPTION_PRICES["fan_30"])
        lei  = info["usd"] * LEI_RATE

        text = (
            "💳 Обмен — выбор карты\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📋 " + info["name"] + " — " + str(info["days"]) + " дней\n"
            "💰 Сумма: " + str(lei) + " лей (" + str(info["usd"]) + " USDT)\n"
            "📈 Курс: 20 лей = 1 USDT\n\n"
            "Выбери тип карты для перевода:"
        )
        safe_edit(bot, call, text, reply_markup=get_exchange_card_keyboard(plan_key))

    # ── Обмен подписки — детали (MC/Visa) ────

    @bot.callback_query_handler(
        func=lambda call: (
            call.data.startswith("mc_sub_") or call.data.startswith("vi_sub_")
        )
    )
    def handle_exchange_sub_card(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        if call.data.startswith("mc_sub_"):
            card     = "Mastercard"
            sub_type = call.data[7:]  # strip "mc_sub_"
        else:
            card     = "Visa"
            sub_type = call.data[7:]  # strip "vi_sub_"

        from utils.payments import SUBSCRIPTION_PRICES
        info = SUBSCRIPTION_PRICES.get(sub_type, SUBSCRIPTION_PRICES["fan_30"])
        lei  = info["usd"] * LEI_RATE

        text = (
            "💳 Оплата через обмен\n"
            "━━━━━━━━━━━━━━━\n\n"
            "📋 Тариф: " + info["name"] + " — " + str(info["days"]) + " дней\n"
            "💰 Сумма: " + str(lei) + " лей (" + str(info["usd"]) + " USDT)\n"
            "💳 Карта: " + card + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📝 Как оплатить:\n\n"
            "1️⃣  Нажми кнопку ниже и напиши @" + EXCHANGE_ADMIN + "\n"
            "2️⃣  Скажи: хочу " + info["name"] + " на " + str(info["days"]) + " дней\n"
            "3️⃣  Переведи " + str(lei) + " лей на карту " + card + "\n"
            "4️⃣  Отправь скриншот перевода\n\n"
            "✅ После подтверждения — подписка активируется!"
        )
        safe_edit(bot, call, text, reply_markup=get_exchange_contact_keyboard())

        username = call.from_user.username
        user_ref = "@" + username if username else "ID " + str(user_id)
        notify_text = (
            "💳 Запрос на обмен — подписка\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 " + user_ref + " (ID: " + str(user_id) + ")\n"
            "📋 " + info["name"] + " — " + str(info["days"]) + " дней\n"
            "💰 " + str(lei) + " лей (" + str(info["usd"]) + " USDT)\n"
            "💳 Карта: " + card
        )
        for admin_id in ADMIN_IDS:
            try: bot.send_message(admin_id, notify_text)
            except Exception as e: print("[EXCHANGE NOTIFY] " + str(e))
        notify_channel(bot, notify_text)

    # ── Меню покупки кристаллов ──────────────

    @bot.callback_query_handler(func=lambda call: call.data == "buy_crystals")
    def buy_crystals_menu(call):
        bot.answer_callback_query(call.id)
        text = (
            "💎 Купить кристаллы\n\n"
            "Кристаллы не сгорают и\n"
            "действуют независимо от подписки!\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💎 50 кристаллов — $5\n"
            "💎 120 кристаллов — $10 (+20 бонус)\n"
            "💎 300 кристаллов — $25 (+50 бонус)\n"
            "💎 650 кристаллов — $50 (+150 бонус)\n"
            "━━━━━━━━━━━━━━━"
        )
        safe_edit(bot, call, text, reply_markup=get_crystal_packs_menu())

    # ── Выбор пакета кристаллов → метод оплаты ──

    @bot.callback_query_handler(func=lambda call: call.data.startswith("crystal_pack_"))
    def handle_crystal_pack(call):
        bot.answer_callback_query(call.id)
        num       = call.data[13:]          # "50" / "120" / "300" / "650"
        pack_type = "pack_" + num           # "pack_50" etc.
        plan_key  = "crystal_pack_" + num   # полный callback для back-кнопки

        from utils.payments import CRYSTAL_PACKS
        info = CRYSTAL_PACKS.get(pack_type, CRYSTAL_PACKS["pack_50"])
        lei  = info["usd"] * LEI_RATE
        total = info["crystals"] + info["bonus"]

        bonus_text = (" (+" + str(info["bonus"]) + " бонус)") if info["bonus"] > 0 else ""
        text = (
            "💎 " + str(total) + " кристаллов" + bonus_text + "\n"
            "━━━━━━━━━━━━━━━\n\n"
            "💰 Стоимость: $" + str(info["usd"]) + " USD\n\n"
            "Выбери способ оплаты:\n\n"
            "🔷 Крипта (LTC) — по актуальному курсу\n"
            "💳 Обмен — " + str(lei) + " лей\n"
            "    (курс: 20 лей = 1 USDT)"
        )
        safe_edit(bot, call, text,
                  reply_markup=get_payment_method_keyboard(plan_key, "buy_crystals"))

    # ── LTC оплата кристаллов ─────────────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ltc_crystal_"))
    def handle_ltc_crystal(call):
        bot.answer_callback_query(call.id, "⏳ Генерируем счёт...")
        num       = call.data[12:]   # strip "ltc_crystal_" → "50" etc.
        pack_type = "pack_" + num
        user_id   = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        invoice = generate_crystal_invoice(pack_type, user_id)
        save_payment(user_id, invoice["payment_id"], pack_type,
                     invoice["amount_ltc"], invoice["amount_usd"], invoice["total_crystals"])
        active_payments[user_id] = invoice

        safe_edit(bot, call, format_payment_message(invoice),
                  reply_markup=get_payment_keyboard(invoice["amount_ltc"], invoice["wallet"]),
                  parse_mode="Markdown")

        notify_text = (
            "🔔 Покупка кристаллов (LTC)\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 User: " + str(user_id) + "\n"
            "💎 Кристаллов: " + str(invoice["total_crystals"]) + "\n"
            "💰 Сумма: " + str(invoice["amount_ltc"]) + " LTC\n"
            "🆔 ID: " + invoice["payment_id"]
        )
        for admin_id in ADMIN_IDS:
            try: bot.send_message(admin_id, notify_text)
            except Exception as e: print("[ADMIN NOTIFY] " + str(e))
        notify_channel(bot, notify_text)

        threading.Thread(target=monitor_payment,
                         args=(bot, call.message.chat.id, user_id, invoice),
                         daemon=True).start()

    # ── Обмен кристаллов → выбор карты ───────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("exch_crystal_"))
    def handle_exchange_crystal(call):
        bot.answer_callback_query(call.id)
        num       = call.data[13:]   # strip "exch_crystal_"
        pack_type = "pack_" + num
        plan_key  = "crystal_pack_" + num

        from utils.payments import CRYSTAL_PACKS
        info  = CRYSTAL_PACKS.get(pack_type, CRYSTAL_PACKS["pack_50"])
        lei   = info["usd"] * LEI_RATE
        total = info["crystals"] + info["bonus"]

        text = (
            "💳 Обмен — выбор карты\n"
            "━━━━━━━━━━━━━━━\n\n"
            "💎 " + str(total) + " кристаллов\n"
            "💰 Сумма: " + str(lei) + " лей (" + str(info["usd"]) + " USDT)\n"
            "📈 Курс: 20 лей = 1 USDT\n\n"
            "Выбери тип карты для перевода:"
        )
        safe_edit(bot, call, text, reply_markup=get_exchange_card_keyboard(plan_key))

    # ── Обмен кристаллов — детали (MC/Visa) ──

    @bot.callback_query_handler(
        func=lambda call: (
            call.data.startswith("mc_crystal_") or call.data.startswith("vi_crystal_")
        )
    )
    def handle_exchange_crystal_card(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        if call.data.startswith("mc_crystal_"):
            card = "Mastercard"
            num  = call.data[11:]   # strip "mc_crystal_"
        else:
            card = "Visa"
            num  = call.data[11:]   # strip "vi_crystal_"

        pack_type = "pack_" + num
        from utils.payments import CRYSTAL_PACKS
        info  = CRYSTAL_PACKS.get(pack_type, CRYSTAL_PACKS["pack_50"])
        lei   = info["usd"] * LEI_RATE
        total = info["crystals"] + info["bonus"]
        bonus_text = (" (+" + str(info["bonus"]) + " бонус)") if info["bonus"] > 0 else ""

        text = (
            "💳 Оплата через обмен\n"
            "━━━━━━━━━━━━━━━\n\n"
            "💎 " + str(total) + " кристаллов" + bonus_text + "\n"
            "💰 Сумма: " + str(lei) + " лей (" + str(info["usd"]) + " USDT)\n"
            "💳 Карта: " + card + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📝 Как оплатить:\n\n"
            "1️⃣  Нажми кнопку ниже и напиши @" + EXCHANGE_ADMIN + "\n"
            "2️⃣  Скажи: хочу купить " + str(total) + " кристаллов\n"
            "3️⃣  Переведи " + str(lei) + " лей на карту " + card + "\n"
            "4️⃣  Отправь скриншот перевода\n\n"
            "✅ После подтверждения — кристаллы зачислятся!"
        )
        safe_edit(bot, call, text, reply_markup=get_exchange_contact_keyboard())

        username = call.from_user.username
        user_ref = "@" + username if username else "ID " + str(user_id)
        notify_text = (
            "💳 Запрос на обмен — кристаллы\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 " + user_ref + " (ID: " + str(user_id) + ")\n"
            "💎 " + str(total) + " кристаллов" + bonus_text + "\n"
            "💰 " + str(lei) + " лей (" + str(info["usd"]) + " USDT)\n"
            "💳 Карта: " + card
        )
        for admin_id in ADMIN_IDS:
            try: bot.send_message(admin_id, notify_text)
            except Exception as e: print("[EXCHANGE NOTIFY] " + str(e))
        notify_channel(bot, notify_text)

    # ── Копировать адрес ─────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "copy_wallet")
    def copy_wallet(call):
        user_id = call.from_user.id
        if user_id in active_payments:
            wallet = active_payments[user_id]["wallet"]
            bot.answer_callback_query(call.id, "Адрес: " + wallet, show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Платёж не найден", show_alert=True)

    # ── Копировать сумму ─────────────────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("copy_amount_"))
    def copy_amount(call):
        amount = call.data.replace("copy_amount_", "")
        bot.answer_callback_query(call.id, "Сумма: " + amount + " LTC", show_alert=True)

    # ── Я оплатил ────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "payment_confirmed")
    def payment_confirmed(call):
        bot.answer_callback_query(call.id, "⏳ Проверяем платёж...", show_alert=True)
        user_id  = call.from_user.id
        chat_id  = call.message.chat.id
        invoice  = active_payments.get(user_id)

        safe_edit(
            bot, call,
            "⏳ Проверяем твой платёж...\n\n"
            "Это может занять до 2 минут.\n"
            "Уведомим как только подтвердится ✅"
        )

        # Немедленная проверка вне основного цикла — не ждём 30 сек
        if invoice:
            threading.Thread(
                target=monitor_payment,
                args=(bot, chat_id, user_id, invoice),
                kwargs={"one_shot": True},
                daemon=True
            ).start()

    # ── История кристаллов ───────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "crystal_history")
    def crystal_history(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        try:
            import psycopg2.extras
            conn   = get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute('''
                SELECT amount, reason, created_at
                FROM crystal_transactions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 15
            ''', (user_id,))
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print("[HISTORY ERROR] " + str(e))
            rows = []

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("◀️ Назад в профиль", callback_data="my_profile")
        )

        if not rows:
            safe_edit(
                bot, call,
                "📊 История транзакций пуста\n\n"
                "Покупай подписки и кристаллы —\n"
                "операции появятся здесь 💎",
                reply_markup=keyboard
            )
            return

        lines = ["📊 История кристаллов (последние 15):\n"]

        for row in rows:
            amount         = row["amount"]
            reason         = row["reason"] or "Операция"
            created_at_raw = row["created_at"]

            try:
                import datetime
                dt       = datetime.datetime.fromtimestamp(int(created_at_raw))
                date_str = dt.strftime("%d.%m %H:%M")
            except Exception:
                date_str = str(created_at_raw)

            sign  = "+" if amount > 0 else ""
            emoji = "✅" if amount > 0 else "💸"
            lines.append(
                emoji + " " + sign + str(amount) + " 💎  " + reason +
                "\n    📅 " + date_str
            )

        safe_edit(bot, call, "\n\n".join(lines), reply_markup=keyboard)
