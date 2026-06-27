# handlers/model_dashboard.py
# Commands for model accounts: /balance, /earnings, /withdraw

import datetime
import time

from telebot import types
from config import ADMIN_IDS
from database import get_user, get_usd_balance, get_connection, _cur
from database.chat_sessions import get_model_active_chats
from database.withdrawals import (
    MIN_WITHDRAWAL_USD,
    request_withdrawal,
    get_model_withdrawals,
)

# FSM state storage: {user_id: {"step": ..., "amount": ..., "address": ...}}
_withdraw_state: dict = {}

LTC_ADDRESS_PREFIXES = ("ltc1", "L", "M", "3")


def _is_model(message) -> bool:
    user = get_user(message.from_user.id)
    return bool(user and user.get("user_role") == "model" and not user.get("is_banned", 0))


def _fmt_date(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%d.%m %H:%M")
    except Exception:
        return "?"


def _get_recent_earnings(user_id: int, limit: int = 5) -> list:
    try:
        conn = get_connection()
        cursor = _cur(conn)
        cursor.execute('''
            SELECT amount_usd, reason, created_at
            FROM balance_transactions
            WHERE user_id = %s AND amount_usd > 0
            ORDER BY created_at DESC
            LIMIT %s
        ''', (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_monthly_earnings(user_id: int) -> float:
    try:
        since = int(time.time()) - 30 * 86400
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(amount_usd), 0)
            FROM balance_transactions
            WHERE user_id = %s AND amount_usd > 0 AND created_at >= %s
        ''', (user_id, since))
        val = cursor.fetchone()[0]
        conn.close()
        return round(float(val), 2)
    except Exception:
        return 0.0


def _get_withdrawn(user_id: int) -> float:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COALESCE(SUM(amount_usd), 0)
            FROM model_withdrawals
            WHERE model_user_id = %s AND status = 'paid'
        ''', (user_id,))
        val = cursor.fetchone()[0]
        conn.close()
        return round(float(val), 2)
    except Exception:
        return 0.0


def register_model_dashboard_handlers(bot):

    # ── /balance ──────────────────────────────

    @bot.message_handler(commands=['balance'], func=_is_model)
    def balance_cmd(message):
        uid = message.from_user.id
        balance = get_usd_balance(uid)
        recent  = _get_recent_earnings(uid)
        chats   = get_model_active_chats(uid)

        lines = [
            "💰 Твой баланс: *$" + str(round(float(balance), 2)) + "*\n",
            "💬 Активных чатов: " + str(len(chats)),
            "",
        ]

        if recent:
            lines.append("Последние зачисления:")
            for r in recent:
                lines.append(
                    "✅ +$" + str(round(r["amount_usd"], 2)) +
                    "  " + _fmt_date(r["created_at"])
                )
        else:
            lines.append("Пока нет зачислений.")

        lines += [
            "",
            "━━━━━━━━━━━━━━━",
            "💸 Минимальный вывод: $" + str(int(MIN_WITHDRAWAL_USD)),
            "Команда: /withdraw",
        ]

        bot.send_message(
            message.chat.id,
            "\n".join(lines),
            parse_mode="Markdown"
        )

    # ── /earnings ─────────────────────────────

    @bot.message_handler(commands=['earnings'], func=_is_model)
    def earnings_cmd(message):
        uid      = message.from_user.id
        monthly  = _get_monthly_earnings(uid)
        withdrawn = _get_withdrawn(uid)
        chats    = get_model_active_chats(uid)
        history  = get_model_withdrawals(uid)

        lines = [
            "📊 *Статистика за 30 дней*\n",
            "💵 Заработано: *$" + str(monthly) + "*",
            "💸 Выведено: $" + str(withdrawn),
            "💬 Активных чатов: " + str(len(chats)),
            "",
        ]

        if history:
            lines.append("История выводов:")
            status_icon = {"pending": "⏳", "paid": "✅", "rejected": "❌", "approved": "🔄"}
            for w in history[:5]:
                icon = status_icon.get(w["status"], "❓")
                lines.append(
                    icon + " $" + str(round(w["amount_usd"], 2)) +
                    " — " + w["status"] + "  " + _fmt_date(w["created_at"])
                )
        else:
            lines.append("Выводов ещё не было.")

        bot.send_message(
            message.chat.id,
            "\n".join(lines),
            parse_mode="Markdown"
        )

    # ── /withdraw ─────────────────────────────

    @bot.message_handler(commands=['withdraw'], func=_is_model)
    def withdraw_cmd(message):
        uid     = message.from_user.id
        balance = float(get_usd_balance(uid))

        if balance < MIN_WITHDRAWAL_USD:
            bot.send_message(
                message.chat.id,
                "❌ Недостаточно средств для вывода.\n\n"
                "Баланс: $" + str(round(balance, 2)) + "\n"
                "Минимум: $" + str(int(MIN_WITHDRAWAL_USD)) + "\n\n"
                "Заработай больше и возвращайся!"
            )
            return

        _withdraw_state[uid] = {"step": "amount", "balance": balance}
        bot.send_message(
            message.chat.id,
            "💸 *Запрос на вывод*\n\n"
            "Твой баланс: *$" + str(round(balance, 2)) + "*\n"
            "Минимальная сумма: $" + str(int(MIN_WITHDRAWAL_USD)) + "\n\n"
            "Введи сумму для вывода (например: 15.00):\n\n"
            "/cancel — отменить",
            parse_mode="Markdown"
        )

    @bot.message_handler(commands=['cancel'], func=lambda m: m.from_user.id in _withdraw_state)
    def cancel_withdraw(message):
        _withdraw_state.pop(message.from_user.id, None)
        bot.send_message(message.chat.id, "❌ Вывод отменён.")

    @bot.message_handler(
        func=lambda m: _is_model(m) and _withdraw_state.get(m.from_user.id, {}).get("step") == "amount"
    )
    def withdraw_amount_input(message):
        uid   = message.from_user.id
        state = _withdraw_state.get(uid, {})
        try:
            amount = round(float(message.text.replace(",", ".")), 2)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Введи число, например: 15.00")
            return

        if amount < MIN_WITHDRAWAL_USD:
            bot.send_message(
                message.chat.id,
                "❌ Минимальная сумма вывода: $" + str(int(MIN_WITHDRAWAL_USD))
            )
            return

        if amount > state["balance"]:
            bot.send_message(
                message.chat.id,
                "❌ Сумма превышает баланс ($" + str(round(state["balance"], 2)) + ")"
            )
            return

        state["amount"] = amount
        state["step"]   = "address"
        _withdraw_state[uid] = state
        bot.send_message(
            message.chat.id,
            "✅ Сумма: *$" + str(amount) + "*\n\n"
            "Теперь введи свой LTC-адрес:\n"
            "(начинается с ltc1, L или M)\n\n"
            "/cancel — отменить",
            parse_mode="Markdown"
        )

    @bot.message_handler(
        func=lambda m: _is_model(m) and _withdraw_state.get(m.from_user.id, {}).get("step") == "address"
    )
    def withdraw_address_input(message):
        uid     = message.from_user.id
        state   = _withdraw_state.get(uid, {})
        address = message.text.strip()

        if not any(address.startswith(p) for p in LTC_ADDRESS_PREFIXES) or len(address) < 20:
            bot.send_message(
                message.chat.id,
                "❌ Некорректный LTC-адрес.\n"
                "Он должен начинаться с ltc1, L или M и быть длиннее 20 символов."
            )
            return

        state["address"] = address
        state["step"]    = "confirm"
        _withdraw_state[uid] = state

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data="wd_confirm"),
            types.InlineKeyboardButton("❌ Отмена",      callback_data="wd_cancel")
        )
        bot.send_message(
            message.chat.id,
            "📋 *Проверь данные:*\n\n"
            "💵 Сумма: *$" + str(state["amount"]) + "*\n"
            "📬 LTC-адрес:\n`" + address + "`\n\n"
            "Всё верно?",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda c: c.data in ("wd_confirm", "wd_cancel"))
    def withdraw_confirm_callback(call):
        bot.answer_callback_query(call.id)
        uid   = call.from_user.id
        state = _withdraw_state.pop(uid, {})

        if call.data == "wd_cancel" or not state:
            try:
                bot.edit_message_text(
                    "❌ Вывод отменён.",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception:
                pass
            return

        if state.get("step") != "confirm":
            return

        try:
            req_id = request_withdrawal(uid, state["amount"], state["address"])
        except Exception as e:
            bot.send_message(uid, "❌ Ошибка при создании заявки: " + str(e))
            return

        try:
            bot.edit_message_text(
                "✅ Заявка на вывод #" + str(req_id) + " отправлена!\n\n"
                "Сумма: *$" + str(state["amount"]) + "*\n"
                "Адрес: `" + state["address"] + "`\n\n"
                "Администратор обработает её в течение 24 часов.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown"
            )
        except Exception:
            bot.send_message(
                uid,
                "✅ Заявка #" + str(req_id) + " на $" + str(state["amount"]) + " отправлена!"
            )

        # Notify all admins
        notify_text = (
            "💸 Запрос на вывод!\n"
            "━━━━━━━━━━━━━━━\n"
            "🆔 Заявка #" + str(req_id) + "\n"
            "👤 Модель: " + str(uid) + "\n"
            "💵 Сумма: $" + str(state["amount"]) + "\n"
            "📬 LTC: " + state["address"] + "\n\n"
            "Команды:\n"
            "/approve " + str(req_id) + "  — одобрить\n"
            "/reject " + str(req_id) + " причина — отклонить"
        )
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, notify_text)
            except Exception as ex:
                print("[MODEL_DASHBOARD] Admin notify error: " + str(ex))
