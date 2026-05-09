# handlers/callback.py
# Все inline-callback хендлеры бота
# Исправлено:
# 1. edit_message_text на фото-сообщениях → используем safe_edit()
# 2. asyncio.new_event_loop() в треде → заменён на asyncio.run()
# 3. monitor_payment теперь не создаёт утечку event loop

import time
import threading
import asyncio

from keyboards.inline import (
    get_main_menu,
    get_subscription_menu,
    get_crystal_packs_menu,
    get_payment_keyboard,
    get_profile_menu
)
from utils.payments import (
    generate_payment_invoice,
    generate_crystal_invoice,
    format_payment_message,
    SUBSCRIPTION_PRICES,
    CRYSTAL_PACKS
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

# Словарь активных платежей: user_id → invoice
active_payments = {}


# ─────────────────────────────────────────────
# Вспомогательная функция — безопасное редактирование
# ─────────────────────────────────────────────

def safe_edit(bot, call, text: str, reply_markup=None, parse_mode=None):
    """
    Безопасно редактирует сообщение.
    Если сообщение содержит фото/медиа — удаляет его и отправляет новое.
    Это решает ошибку: 'there is no text in the message to edit'
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
        # Telegram не даёт редактировать фото-сообщения как текст
        if "there is no text" in err or "message can't be edited" in err or "message to edit not found" in err:
            try:
                bot.delete_message(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id
                )
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
# Мониторинг платежа в отдельном треде
# ─────────────────────────────────────────────

def monitor_payment(bot, chat_id: int, user_id: int, invoice: dict):
    """
    Фоновый поток — проверяет поступление LTC каждые 30 секунд.
    Максимальное время ожидания — 60 минут.
    Исправлено: используем asyncio.run() вместо создания нового event loop.
    """
    expected_amount = invoice["amount_ltc"]
    payment_id = invoice["payment_id"]
    invoice_type = invoice.get("type", "subscription")
    timeout = 3600       # 60 минут максимум
    check_interval = 30  # проверяем каждые 30 секунд
    start_time = time.time()

    print("[MONITOR] Старт мониторинга платежа " + payment_id)

    while time.time() - start_time < timeout:
        try:
            # asyncio.run() — правильный способ запуска корутины в треде
            payment_received, amount = asyncio.run(
                check_payment(LTC_ADDRESS, expected_amount)
            )

            if payment_received:
                confirm_payment(payment_id)

                if invoice_type == "subscription":
                    sub_type = invoice["sub_type"]
                    days = invoice["days"]
                    crystals = invoice["crystals"]
                    sub_name = invoice["sub_name"]

                    activate_subscription(user_id, sub_type, days, crystals)

                    bot.send_message(
                        chat_id,
                        "✅ ПЛАТЁЖ ПОДТВЕРЖДЁН!\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "🎉 Подписка " + sub_name + " активирована!\n"
                        "⏰ Срок: " + str(days) + " дней\n"
                        "💎 Начислено: " + str(crystals) + " кристаллов\n\n"
                        "Добро пожаловать в клуб! ❤️",
                        reply_markup=get_main_menu()
                    )
                else:
                    total_crystals = invoice["total_crystals"]
                    pack_name = invoice["pack_name"]
                    add_crystals(user_id, total_crystals, "Покупка пакета " + pack_name)
                    bot.send_message(
                        chat_id,
                        "✅ ПЛАТЁЖ ПОДТВЕРЖДЁН!\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "💎 Начислено: " + str(total_crystals) + " кристаллов\n\n"
                        "Приятного использования! ✨",
                        reply_markup=get_main_menu()
                    )

                # Уведомляем всех админов
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

                # Удаляем из активных платежей
                active_payments.pop(user_id, None)
                print("[MONITOR] Платёж " + payment_id + " подтверждён!")
                return

            time.sleep(check_interval)

        except Exception as e:
            print("[MONITOR ERROR] " + str(e))
            time.sleep(check_interval)

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
        """Возврат в главное меню — работает и с фото и с текстом"""
        safe_edit(bot, call, "❤️ Главное меню", reply_markup=get_main_menu())

    # ── О системе кристаллов ─────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "about_system")
    def about_system(call):
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
        user_id = call.from_user.id
        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )

        user = get_user(user_id)
        sub = check_subscription(user_id)
        days_reg = get_days_since_registration(user_id)

        if sub["active"]:
            if "premium" in sub["type"]:
                sub_text = "👑 Premium • " + str(sub["days_left"]) + " дней"
            else:
                sub_text = "🌸 Fan • " + str(sub["days_left"]) + " дней"
        else:
            sub_text = "❌ Нет подписки"

        crystals = user.get("crystals", 0) if user else 0
        profiles_viewed = user.get("profiles_viewed", 0) if user else 0
        favorites = user.get("favorites_count", 0) if user else 0
        gifts = user.get("gifts_sent", 0) if user else 0

        username = call.from_user.username
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

        has_premium = sub["active"] and "premium" in sub.get("type", "")
        safe_edit(bot, call, text, reply_markup=get_profile_menu(has_premium))

    # ── Меню подписок ────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "subscription")
    def subscription_menu(call):
        user_id = call.from_user.id
        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )

        sub = check_subscription(user_id)

        if sub["active"]:
            sub_name = "👑 Premium" if "premium" in sub["type"] else "🌸 Fan"
            text = (
                "💎 Твоя подписка\n\n"
                "Тип: " + sub_name + "\n"
                "⏰ Осталось: " + str(sub["days_left"]) + " дней\n\n"
                "Хочешь продлить или сменить тариф?\n\n"
                "━━━━━━━━━━━━━━━\n"
                "🌸 Fan — 30 дней • $25 • 250 💎\n"
                "• 3 фото каждой модели\n"
                "• Просмотр каталога\n\n"
                "👑 Premium — 90 дней • $50 • 600 💎\n"
                "• Все фото и видео\n"
                "• Эксклюзивный контент\n"
                "• Приоритет в каталоге"
            )
        else:
            text = (
                "💎 Выбери подписку\n\n"
                "━━━━━━━━━━━━━━━\n"
                "🌸 Fan — 30 дней • $25\n"
                "• 📸 3 фото каждой модели\n"
                "• 💎 250 кристаллов\n"
                "• 👁 Просмотр каталога\n"
                "• 💬 Чат с моделями (10 💎)\n\n"
                "━━━━━━━━━━━━━━━\n"
                "👑 Premium — 90 дней • $50\n"
                "• 📸 Все фото и видео\n"
                "• 💎 600 кристаллов\n"
                "• 🔓 Эксклюзивный контент\n"
                "• 💬 Чат с моделями (10 💎)\n"
                "• 🎁 Подарки моделям (20 💎)\n"
                "• ⭐ Приоритет в каталоге\n"
                "━━━━━━━━━━━━━━━"
            )

        safe_edit(bot, call, text, reply_markup=get_subscription_menu())

    # ── Выбор подписки → генерация инвойса ──

    @bot.callback_query_handler(func=lambda call: call.data.startswith("sub_"))
    def handle_subscription(call):
        sub_type = call.data.replace("sub_", "")
        user_id = call.from_user.id

        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )

        invoice = generate_payment_invoice(sub_type, user_id)

        save_payment(
            user_id,
            invoice["payment_id"],
            sub_type,
            invoice["amount_ltc"],
            invoice["amount_usd"],
            invoice["crystals"]
        )

        active_payments[user_id] = invoice

        safe_edit(
            bot, call,
            format_payment_message(invoice),
            reply_markup=get_payment_keyboard(invoice["amount_ltc"], invoice["wallet"]),
            parse_mode="Markdown"
        )

        # Уведомляем админов о новом счёте
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    "🔔 Новый счёт на подписку\n\n"
                    "👤 User: " + str(user_id) + "\n"
                    "💳 Тариф: " + invoice["sub_name"] + "\n"
                    "💰 Сумма: " + str(invoice["amount_ltc"]) + " LTC\n"
                    "💎 Кристаллов: " + str(invoice["crystals"]) + "\n"
                    "🆔 ID: " + invoice["payment_id"]
                )
            except Exception as e:
                print("[ADMIN NOTIFY ERROR] " + str(e))

        # Запускаем мониторинг платежа в фоне
        thread = threading.Thread(
            target=monitor_payment,
            args=(bot, call.message.chat.id, user_id, invoice),
            daemon=True
        )
        thread.start()

    # ── Меню покупки кристаллов ──────────────

    @bot.callback_query_handler(func=lambda call: call.data == "buy_crystals")
    def buy_crystals_menu(call):
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

    # ── Выбор пакета кристаллов ──────────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("crystal_pack_"))
    def handle_crystal_pack(call):
        pack_type = call.data.replace("crystal_", "")
        user_id = call.from_user.id

        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )

        invoice = generate_crystal_invoice(pack_type, user_id)
        active_payments[user_id] = invoice

        save_payment(
            user_id,
            invoice["payment_id"],
            pack_type,
            invoice["amount_ltc"],
            invoice["amount_usd"],
            invoice["total_crystals"]
        )

        safe_edit(
            bot, call,
            format_payment_message(invoice),
            reply_markup=get_payment_keyboard(invoice["amount_ltc"], invoice["wallet"]),
            parse_mode="Markdown"
        )

        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    "🔔 Покупка кристаллов\n\n"
                    "👤 User: " + str(user_id) + "\n"
                    "💎 Кристаллов: " + str(invoice["total_crystals"]) + "\n"
                    "💰 Сумма: " + str(invoice["amount_ltc"]) + " LTC\n"
                    "🆔 ID: " + invoice["payment_id"]
                )
            except Exception as e:
                print("[ADMIN NOTIFY ERROR] " + str(e))

        thread = threading.Thread(
            target=monitor_payment,
            args=(bot, call.message.chat.id, user_id, invoice),
            daemon=True
        )
        thread.start()

    # ── Копировать адрес кошелька ────────────

    @bot.callback_query_handler(func=lambda call: call.data == "copy_wallet")
    def copy_wallet(call):
        user_id = call.from_user.id
        if user_id in active_payments:
            wallet = active_payments[user_id]["wallet"]
            bot.answer_callback_query(
                call.id,
                "Адрес: " + wallet,
                show_alert=True
            )
        else:
            bot.answer_callback_query(call.id, "❌ Платёж не найден", show_alert=True)

    # ── Копировать сумму ─────────────────────

    @bot.callback_query_handler(func=lambda call: call.data.startswith("copy_amount_"))
    def copy_amount(call):
        amount = call.data.replace("copy_amount_", "")
        bot.answer_callback_query(
            call.id,
            "Сумма: " + amount + " LTC",
            show_alert=True
        )

    # ── Нажал "Я оплатил" ───────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "payment_confirmed")
    def payment_confirmed(call):
        bot.answer_callback_query(call.id, "⏳ Проверяем платёж...", show_alert=True)
        safe_edit(
            bot, call,
            "⏳ Проверяем твой платёж...\n\n"
            "Это может занять до 5 минут.\n"
            "Уведомим как только подтвердится ✅"
        )

    # ── История транзакций ───────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "crystal_history")
    def crystal_history(call):
        user_id = call.from_user.id
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT amount, reason, created_at
            FROM crystal_transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        ''', (user_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            bot.answer_callback_query(call.id, "История пуста", show_alert=True)
            return

        text = "📊 История транзакций:\n\n"
        for row in rows:
            sign = "+" if row[0] > 0 else ""
            text += sign + str(row[0]) + " 💎 — " + row[1] + "\n"

        bot.send_message(call.message.chat.id, text)
