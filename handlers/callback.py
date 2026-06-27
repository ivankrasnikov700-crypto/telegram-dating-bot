# handlers/callback.py
# Inline-callback хендлеры бота (v3 — USD balance + чат-сессии)

import time
import threading

from keyboards.inline import (
    get_main_menu,
    get_topup_menu,
    get_payment_keyboard,
    get_profile_menu,
)
from utils.payments import (
    generate_topup_invoice,
    format_payment_message,
)
from utils.blockchain import check_payment
from database import (
    register_user,
    get_user,
    add_usd_balance,
    get_usd_balance,
    save_payment,
    confirm_payment,
    get_days_since_registration,
    get_connection,
    is_banned,
    save_pending_payment,
    load_all_pending_payments,
    delete_pending_payment,
)
from database.chat_sessions import get_fan_active_chats
from config import LTC_ADDRESS, ADMIN_IDS
from utils.notify import notify_channel
from telebot import types
import time as _time

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
    Фоновый поток — проверяет LTC каждые 30 секунд до истечения инвойса.
    one_shot=True — одиночная проверка без цикла (вызывается при нажатии «Я оплатил»).
    """
    expected_amount = invoice["amount_ltc"]
    payment_id      = invoice["payment_id"]
    invoice_type    = invoice.get("type", "topup")
    created_at      = invoice.get("created_at", int(time.time()))
    expires_at      = invoice.get("expires_at", int(time.time()) + 3600)
    check_interval  = 30

    print("[MONITOR] Старт мониторинга " + payment_id +
          " сумма " + str(expected_amount) + " LTC")

    while int(time.time()) < expires_at:
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
                        return
                    confirm_payment(payment_id)

                if invoice_type == "topup":
                    add_usd_balance(user_id, float(invoice["amount_usd"]), "Пополнение LTC")
                    bot.send_message(
                        chat_id,
                        "✅ БАЛАНС ПОПОЛНЕН!\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n"
                        "💵 Зачислено: $" + str(invoice["amount_usd"]) + " USD\n\n"
                        "Используй баланс для чатов с моделями 💬",
                        reply_markup=get_main_menu()
                    )
                    notify_channel(
                        bot,
                        "✅ Пополнение баланса!\n"
                        "━━━━━━━━━━━━━━━\n"
                        "👤 User: " + str(user_id) + "\n"
                        "💵 Зачислено: $" + str(invoice["amount_usd"]) + "\n"
                        "💰 Сумма: " + str(amount) + " LTC\n"
                        "🆔 ID: " + payment_id
                    )
                else:
                    # Legacy subscription/crystal invoice — уведомить и игнорировать
                    bot.send_message(
                        chat_id,
                        "✅ Платёж получен!\n\n"
                        "💰 Получено: " + str(amount) + " LTC\n\n"
                        "Обратитесь к администратору для зачисления.",
                        reply_markup=get_main_menu()
                    )

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

                active_payments.pop(user_id, None)
                delete_pending_payment(user_id)
                print("[MONITOR] Платёж " + payment_id + " подтверждён!")
                return

            if one_shot:
                return
            time.sleep(check_interval)

        except Exception as e:
            print("[MONITOR ERROR] " + str(e))
            if one_shot:
                return
            time.sleep(check_interval)

    if one_shot:
        return

    bot.send_message(
        chat_id,
        "⏰ Время истекло\n\n"
        "Счёт более не действителен.\n"
        "Создай новый через «Пополнить баланс»."
    )
    active_payments.pop(user_id, None)
    delete_pending_payment(user_id)
    print("[MONITOR] Платёж " + payment_id + " истёк")


# ─────────────────────────────────────────────
# Регистрация хендлеров
# ─────────────────────────────────────────────

def register_callback_handlers(bot):

    # ── Проверка бана (первый обработчик) ────

    @bot.callback_query_handler(func=lambda call: is_banned(call.from_user.id))
    def banned_user_callback(call):
        bot.answer_callback_query(call.id, "🚫 Ваш аккаунт заблокирован.", show_alert=True)

    # ── Назад в главное меню ─────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
    def back_to_main(call):
        bot.answer_callback_query(call.id)
        safe_edit(bot, call, "❤️ Главное меню", reply_markup=get_main_menu())

    # ── О системе ────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "about_system")
    def about_system(call):
        bot.answer_callback_query(call.id)
        text = (
            "ℹ️ Miss Moldova — как это работает\n\n"
            "Платформа для прямого общения с моделями.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💵 Пополнение баланса:\n"
            "   $10 / $25 / $50 через LTC (Litecoin)\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💬 Чат с моделью:\n"
            "   $5 — 24 часа неограниченного общения\n"
            "   70% получает модель\n"
            "   30% — платформа\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🔒 Анонимность:\n"
            "   Бот не раскрывает контакты\n"
            "   Всё общение через платформу\n\n"
            "━━━━━━━━━━━━━━━\n"
            "👑 VIP Клуб:\n"
            "   Расписание живых сессий\n"
            "   Анонсы и Q&A с моделями"
        )
        safe_edit(bot, call, text, reply_markup=get_main_menu())

    # ── Мой профиль ──────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "my_profile")
    def my_profile(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        user     = get_user(user_id)
        days_reg = get_days_since_registration(user_id)
        balance  = float(user.get("balance_usd", 0.0)) if user else 0.0

        active_chats = get_fan_active_chats(user_id)

        username  = call.from_user.username
        name_text = "@" + username if username else call.from_user.full_name

        if active_chats:
            chats_lines = []
            for ch in active_chats:
                remaining = max(0, ch["expires_at"] - int(time.time()))
                hours_left = remaining // 3600
                from database.models import get_model
                model = get_model(ch["model_id"])
                model_name = model.get("name", "Модель " + str(ch["model_id"])) if model else "Модель"
                chats_lines.append("💬 " + model_name + " — ещё " + str(hours_left) + "ч")
            chats_text = "\n".join(chats_lines)
        else:
            chats_text = "❌ Нет активных чатов"

        text = (
            "👤 Профиль участника\n"
            "━━━━━━━━━━━━━━━\n\n"
            "🏷 " + name_text + "\n"
            "🆔 ID: " + str(user_id) + "\n"
            "📅 В клубе: " + str(days_reg) + " дней\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💵 Баланс: $" + str(round(balance, 2)) + " USD\n\n"
            "━━━━━━━━━━━━━━━\n"
            "Активные чаты:\n" + chats_text + "\n"
            "━━━━━━━━━━━━━━━"
        )

        safe_edit(bot, call, text, reply_markup=get_profile_menu())

    # ── Пополнить баланс ─────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "topup_balance")
    def topup_balance(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        balance = get_usd_balance(user_id)
        text = (
            "💵 Пополнение баланса\n\n"
            "Текущий баланс: $" + str(round(balance, 2)) + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "Выбери сумму пополнения:\n\n"
            "Оплата принимается в LTC (Litecoin).\n"
            "После подтверждения баланс пополнится."
        )
        safe_edit(bot, call, text, reply_markup=get_topup_menu())

    # ── Выбор суммы пополнения ───────────────

    @bot.callback_query_handler(
        func=lambda call: (
            call.data.startswith("topup_") and call.data[6:].isdigit()
        )
    )
    def handle_topup_amount(call):
        bot.answer_callback_query(call.id, "⏳ Генерируем счёт...")
        amount_usd = int(call.data[6:])
        user_id    = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        invoice = generate_topup_invoice(amount_usd, user_id)
        save_payment(user_id, invoice["payment_id"], "topup",
                     invoice["amount_ltc"], invoice["amount_usd"])
        active_payments[user_id] = invoice
        save_pending_payment(user_id, call.message.chat.id, invoice)

        safe_edit(bot, call, format_payment_message(invoice),
                  reply_markup=get_payment_keyboard(invoice["amount_ltc"], invoice["wallet"]),
                  parse_mode="Markdown")

        notify_text = (
            "🔔 Пополнение баланса (LTC)\n"
            "━━━━━━━━━━━━━━━\n"
            "👤 User: " + str(user_id) + "\n"
            "💵 Сумма: $" + str(amount_usd) + "\n"
            "💰 LTC: " + str(invoice["amount_ltc"]) + "\n"
            "🆔 ID: " + invoice["payment_id"]
        )
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, notify_text)
            except Exception as e:
                print("[ADMIN NOTIFY] " + str(e))
        notify_channel(bot, notify_text)

        threading.Thread(
            target=monitor_payment,
            args=(bot, call.message.chat.id, user_id, invoice),
            daemon=True
        ).start()

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

        if invoice:
            threading.Thread(
                target=monitor_payment,
                args=(bot, chat_id, user_id, invoice),
                kwargs={"one_shot": True},
                daemon=True
            ).start()

    # ── История транзакций ───────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "tx_history")
    def tx_history(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id

        try:
            import psycopg2.extras
            conn   = get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute('''
                SELECT amount_usd, reason, created_at
                FROM balance_transactions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 15
            ''', (user_id,))
            rows = cursor.fetchall()
            conn.close()
        except Exception as e:
            print("[TX HISTORY ERROR] " + str(e))
            rows = []

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("◀️ Назад в профиль", callback_data="my_profile")
        )

        if not rows:
            safe_edit(
                bot, call,
                "📊 История транзакций пуста\n\n"
                "Пополни баланс и купи чат с моделью —\n"
                "операции появятся здесь 💬",
                reply_markup=keyboard
            )
            return

        import datetime
        lines = ["📊 История транзакций (последние 15):\n"]
        for row in rows:
            amount    = row["amount_usd"]
            reason    = row["reason"] or "Операция"
            created   = row["created_at"]
            try:
                dt       = datetime.datetime.fromtimestamp(int(created))
                date_str = dt.strftime("%d.%m %H:%M")
            except Exception:
                date_str = str(created)

            sign  = "+" if amount > 0 else ""
            emoji = "✅" if amount > 0 else "💸"
            lines.append(
                emoji + " " + sign + "$" + str(round(amount, 2)) + "  " + reason +
                "\n    📅 " + date_str
            )

        safe_edit(bot, call, "\n\n".join(lines), reply_markup=keyboard)


# ─────────────────────────────────────────────
# Восстановление платежей после рестарта
# ─────────────────────────────────────────────

def restore_pending_payments(bot):
    """
    Called once on startup. Loads un-expired pending payments from DB,
    populates active_payments dict, and resumes monitoring threads.
    """
    pending = load_all_pending_payments()
    if not pending:
        return

    print("[MONITOR] Восстанавливаем " + str(len(pending)) + " платежей после рестарта")
    for entry in pending:
        user_id = entry["user_id"]
        chat_id = entry["chat_id"]
        invoice = entry["invoice"]
        active_payments[user_id] = invoice
        threading.Thread(
            target=monitor_payment,
            args=(bot, chat_id, user_id, invoice),
            daemon=True
        ).start()
        print("[MONITOR] Возобновлён мониторинг " + invoice.get("payment_id", "?") +
              " для user " + str(user_id))
