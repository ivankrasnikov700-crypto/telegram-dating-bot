# handlers/callback.py
# Обработчики всех callback-запросов от inline-кнопок

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
    get_days_since_registration
)
from config import LTC_ADDRESS, ADMIN_IDS

# Хранилище активных платежей {user_id: invoice}
active_payments = {}


def register_callback_handlers(bot):

    # ═══════════════════════════════
    # ГЛАВНОЕ МЕНЮ
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
    def back_to_main(call):
        """Возврат в главное меню"""
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❤️ Главное меню",
            reply_markup=get_main_menu()
        )

    # ═══════════════════════════════
    # О СИСТЕМЕ
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "about_system")
    def about_system(call):
        """Информация о системе кристаллов"""
        text = (
            "💎 *Система кристаллов Miss Moldova*\n\n"
            "Кристаллы — внутренняя валюта клуба.\n"
            "Получай их с подпиской или покупай отдельно!\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💳 *Подписки:*\n"
            "🌸 Fan 30 дней — $25 → 250 💎\n"
            "👑 Premium 90 дней — $50 → 600 💎\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📦 *Пакеты кристаллов:*\n"
            "💎 50 кристаллов — $5\n"
            "💎 120 кристаллов — $10 (+20 бонус)\n"
            "💎 300 кристаллов — $25 (+50 бонус)\n"
            "💎 650 кристаллов — $50 (+150 бонус)\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🛍 *На что тратить:*\n"
            "💬 Написать модели — 10 💎\n"
            "❤️ Разблокировать фото — 5 💎\n"
            "🎁 Подарок модели — 20 💎\n"
            "🔓 Эксклюзивный контент — 15 💎\n"
            "👁 Просмотр без подписки — 3 💎\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💡 Кристаллы не сгорают!\n"
            "Используй их в любое время ✨"
        )
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )

    # ═══════════════════════════════
    # ПРОФИЛЬ
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "my_profile")
    def my_profile(call):
        """Красивый профиль пользователя"""
        user_id = call.from_user.id

        register_user(
            user_id,
            call.from_user.username or "",
            call.from_user.full_name or ""
        )

        user = get_user(user_id)
        sub = check_subscription(user_id)
        days_reg = get_days_since_registration(user_id)

        # Статус подписки
        if sub["active"]:
            if "premium" in sub["type"]:
                sub_text = "👑 Premium • " + str(sub["days_left"]) + " дней"
            else:
                sub_text = "🌸 Fan • " + str(sub["days_left"]) + " дней"
        else:
            sub_text = "❌ Нет подписки"

        # Кристаллы
        crystals = user.get("crystals", 0) if user else 0

        # Статистика
        profiles_viewed = user.get("profiles_viewed", 0) if user else 0
        favorites = user.get("favorites_count", 0) if user else 0
        gifts = user.get("gifts_sent", 0) if user else 0

        # Username
        username = call.from_user.username
        name_text = "@" + username if username else call.from_user.full_name

        text = (
            "👤 *Профиль участника*\n"
            "━━━━━━━━━━━━━━━\n\n"
            "🏷 " + name_text + "\n"
            "🆔 ID: `" + str(user_id) + "`\n"
            "📅 В клубе: *" + str(days_reg) + " дней*\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💎 *Баланс:* " + str(crystals) + " кристаллов\n"
            "🎫 *Подписка:* " + sub_text + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📊 *Статистика:*\n"
            "👁 Просмотрено профилей: *" + str(profiles_viewed) + "*\n"
            "❤️ В избранном: *" + str(favorites) + "*\n"
            "🎁 Подарков отправлено: *" + str(gifts) + "*\n"
            "━━━━━━━━━━━━━━━"
        )

        has_premium = sub["active"] and "premium" in sub.get("type", "")

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_profile_menu(has_premium),
            parse_mode="Markdown"
        )

    # ═══════════════════════════════
    # ПОДПИСКИ
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "subscription")
    def subscription_menu(call):
        """Показывает меню подписок"""
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
                "💎 *Твоя подписка*\n\n"
                "Тип: *" + sub_name + "*\n"
                "⏰ Осталось: *" + str(sub["days_left"]) + " дней*\n\n"
                "Хочешь продлить или сменить тариф?\n\n"
                "━━━━━━━━━━━━━━━\n"
                "🌸 *Fan* — 30 дней • $25 • 250 💎\n"
                "• 3 фото каждой модели\n"
                "• Просмотр каталога\n\n"
                "👑 *Premium* — 90 дней • $50 • 600 💎\n"
                "• Все фото и видео\n"
                "• Эксклюзивный контент\n"
                "• Приоритет в каталоге"
            )
        else:
            text = (
                "💎 *Выбери подписку*\n\n"
                "━━━━━━━━━━━━━━━\n"
                "🌸 *Fan* — 30 дней • $25\n"
                "• 📸 3 фото каждой модели\n"
                "• 💎 250 кристаллов\n"
                "• 👁 Просмотр каталога\n"
                "• 💬 Чат с моделями (10 💎)\n\n"
                "━━━━━━━━━━━━━━━\n"
                "👑 *Premium* — 90 дней • $50\n"
                "• 📸 Все фото и видео\n"
                "• 💎 600 кристаллов\n"
                "• 🔓 Эксклюзивный контент\n"
                "• 💬 Чат с моделями (10 💎)\n"
                "• 🎁 Подарки моделям (20 💎)\n"
                "• ⭐ Приоритет в каталоге\n"
                "━━━━━━━━━━━━━━━"
            )

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_subscription_menu(),
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("sub_"))
    def handle_subscription(call):
        """Генерация счёта на подписку"""
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

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=format_payment_message(invoice),
            reply_markup=get_payment_keyboard(
                invoice["amount_ltc"],
                invoice["wallet"]
            ),
            parse_mode="Markdown"
        )

        # Уведомляем админа
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    "🔔 *Новый счёт на подписку*\n\n"
                    "👤 User: " + str(user_id) + "\n"
                    "💳 Тариф: " + invoice["sub_name"] + "\n"
                    "💰 Сумма: " + str(invoice["amount_ltc"]) + " LTC\n"
                    "💎 Кристаллов: " + str(invoice["crystals"]) + "\n"
                    "🆔 ID: " + invoice["payment_id"],
                    parse_mode="Markdown"
                )
            except Exception as e:
                print("[ADMIN NOTIFY ERROR] " + str(e))

        # Запускаем мониторинг
        thread = threading.Thread(
            target=monitor_payment,
            args=(bot, call.message.chat.id, user_id, invoice)
        )
        thread.daemon = True
        thread.start()

    # ═══════════════════════════════
    # КРИСТАЛЛЫ
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "buy_crystals")
    def buy_crystals_menu(call):
        """Меню покупки кристаллов"""
        text = (
            "💎 *Купить кристаллы*\n\n"
            "Кристаллы не сгорают и\n"
            "действуют независимо от подписки!\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💎 50 кристаллов — $5\n"
            "💎 120 кристаллов — $10 *(+20 бонус)*\n"
            "💎 300 кристаллов — $25 *(+50 бонус)*\n"
            "💎 650 кристаллов — $50 *(+150 бонус)*\n"
            "━━━━━━━━━━━━━━━"
        )
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=get_crystal_packs_menu(),
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("crystal_pack_"))
    def handle_crystal_pack(call):
        """Генерация счёта на покупку кристаллов"""
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

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=format_payment_message(invoice),
            reply_markup=get_payment_keyboard(
                invoice["amount_ltc"],
                invoice["wallet"]
            ),
            parse_mode="Markdown"
        )

        # Уведомляем админа
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    "🔔 *Покупка кристаллов*\n\n"
                    "👤 User: " + str(user_id) + "\n"
                    "💎 Кристаллов: " + str(invoice["total_crystals"]) + "\n"
                    "💰 Сумма: " + str(invoice["amount_ltc"]) + " LTC\n"
                    "🆔 ID: " + invoice["payment_id"],
                    parse_mode="Markdown"
                )
            except Exception as e:
                print("[ADMIN NOTIFY ERROR] " + str(e))

        # Запускаем мониторинг
        thread = threading.Thread(
            target=monitor_payment,
            args=(bot, call.message.chat.id, user_id, invoice)
        )
        thread.daemon = True
        thread.start()

    # ═══════════════════════════════
    # ОПЛАТА
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "copy_wallet")
    def copy_wallet(call):
        """Копирование адреса кошелька"""
        user_id = call.from_user.id
        if user_id in active_payments:
            wallet = active_payments[user_id]["wallet"]
            bot.answer_callback_query(
                call.id,
                "Адрес: " + wallet,
                show_alert=True
            )
        else:
            bot.answer_callback_query(
                call.id,
                "❌ Платёж не найден",
                show_alert=True
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("copy_amount_"))
    def copy_amount(call):
        """Копирование суммы"""
        amount = call.data.replace("copy_amount_", "")
        bot.answer_callback_query(
            call.id,
            "Сумма: " + amount + " LTC",
            show_alert=True
        )

    @bot.callback_query_handler(func=lambda call: call.data == "payment_confirmed")
    def payment_confirmed(call):
        """Пользователь нажал Я оплатил"""
        bot.answer_callback_query(
            call.id,
            "⏳ Проверяем платёж...",
            show_alert=True
        )
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="⏳ *Проверяем твой платёж...*\n\n"
                 "Это может занять до 5 минут.\n"
                 "Уведомим как только подтвердится ✅",
            parse_mode="Markdown"
        )

    # ═══════════════════════════════
    # ДЕВУШКИ
    # ═══════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "girls")
    def girls_handler(call):
        """Каталог девушек"""
        user_id = call.from_user.id
        sub = check_subscription(user_id)

        if not sub["active"]:
            bot.answer_callback_query(
                call.id,
                "🔒 Нужна подписка Fan или Premium!",
                show_alert=True
            )
            return

        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="👭 *Каталог моделей*\n\n"
                 "🚀 Скоро здесь появятся профили!\n"
                 "Следи за обновлениями 🔥",
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )


def monitor_payment(bot, chat_id: int, user_id: int, invoice: dict):
    """Мониторинг платежа в отдельном потоке"""
    expected_amount = invoice["amount_ltc"]
    payment_id = invoice["payment_id"]
    invoice_type = invoice.get("type", "subscription")
    timeout = 3600
    check_interval = 30
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            payment_received, amount = loop.run_until_complete(
                check_payment(LTC_ADDRESS, expected_amount)
            )
            loop.close()

            if payment_received:
                print("[SUCCESS] Платёж получен от user " + str(user_id))

                confirm_payment(payment_id)

                if invoice_type == "subscription":
                    sub_type = invoice["sub_type"]
                    days = invoice["days"]
                    crystals = invoice["crystals"]
                    sub_name = invoice["sub_name"]

                    activate_subscription(user_id, sub_type, days, crystals)

                    bot.send_message(
                        chat_id,
                        "✅ *ПЛАТЁЖ ПОДТВЕРЖДЁН!*\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "🎉 Подписка *" + sub_name + "* активирована!\n"
                        "⏰ Срок: *" + str(days) + " дней*\n"
                        "💎 Начислено: *" + str(crystals) + " кристаллов*\n\n"
                        "Добро пожаловать в клуб! ❤️",
                        parse_mode="Markdown",
                        reply_markup=get_main_menu()
                    )

                else:
                    # Покупка кристаллов
                    total_crystals = invoice["total_crystals"]
                    pack_name = invoice["pack_name"]

                    add_crystals(user_id, total_crystals, "Покупка пакета " + pack_name)

                    bot.send_message(
                        chat_id,
                        "✅ *ПЛАТЁЖ ПОДТВЕРЖДЁН!*\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "💎 Начислено: *" + str(total_crystals) + " кристаллов*\n\n"
                        "Приятного использования! ✨",
                        parse_mode="Markdown",
                        reply_markup=get_main_menu()
                    )

                # Уведомляем админа
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(
                            admin_id,
                            "✅ *Платёж подтверждён!*\n\n"
                            "👤 User: " + str(user_id) + "\n"
                            "💰 Сумма: " + str(amount) + " LTC\n"
                            "🆔 ID: " + payment_id,
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        print("[ADMIN NOTIFY ERROR] " + str(e))

                if user_id in active_payments:
                    del active_payments[user_id]

                return

            time.sleep(check_interval)

        except Exception as e:
            print("[ERROR] Мониторинг: " + str(e))
            time.sleep(check_interval)

    # Время истекло
    bot.send_message(
        chat_id,
        "⏰ *Время истекло*\n\n"
        "Счёт более не действителен.\n"
        "Создай новый в меню подписок.",
        parse_mode="Markdown"
    )

    if user_id in active_payments:
        del active_payments[user_id]