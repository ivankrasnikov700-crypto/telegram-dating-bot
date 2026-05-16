from database.bonus import claim_daily_bonus, get_bonus_info, BONUS_AMOUNTS
from database import register_user
from telebot import types


def _build_streak_bar(streak: int) -> str:
    """Визуальный прогресс-бар стрика 1-7."""
    filled = "🔥" * streak
    empty  = "⬜" * (7 - streak)
    return filled + empty


def _format_bonus_info(user_id: int) -> str:
    """Формирует текст состояния бонуса без попытки получить."""
    import time
    info    = get_bonus_info(user_id)
    streak  = info["bonus_streak"] or 0
    last    = info["last_bonus_at"] or 0
    elapsed = time.time() - last

    bar        = _build_streak_bar(min(streak, 7))
    next_day   = (streak % 7) + 1 if streak > 0 else 1
    next_amt   = BONUS_AMOUNTS.get(next_day, 10)

    if last == 0:
        status_line = "🎁 Твой первый бонус — получи прямо сейчас!"
    elif elapsed >= 86400:
        status_line = "✅ Бонус готов к получению!"
    else:
        hours_left = (86400 - elapsed) / 3600
        h = int(hours_left)
        mn = int((hours_left - h) * 60)
        status_line = "⏳ Следующий бонус через " + str(h) + " ч " + str(mn) + " мин"

    return (
        "🎁 Ежедневный бонус\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📅 Стрик: День " + str(streak) + " из 7\n"
        + bar + "\n\n"
        + status_line + "\n\n"
        "💎 Награды по дням:\n"
        "  День 1: +3 💎\n"
        "  День 2: +5 💎\n"
        "  День 3: +7 💎\n"
        "  День 4–6: +10 💎\n"
        "  День 7: +30 💎 🎊\n\n"
        "Заходи каждый день — на 7-й день джекпот!"
    )


def register_bonus_handlers(bot):

    @bot.callback_query_handler(func=lambda call: call.data == "daily_bonus")
    def daily_bonus_handler(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        result = claim_daily_bonus(user_id)

        back_kb = types.InlineKeyboardMarkup()
        back_kb.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu"))

        if result["success"]:
            streak   = result["streak"]
            crystals = result["crystals"]
            bar      = _build_streak_bar(streak)

            if result.get("is_week_complete"):
                header = "🎊 Ты завершил неделю! Новый цикл начат!"
            elif streak == 7:
                header = "🏆 ДЕНЬ 7 — МАКСИМАЛЬНЫЙ БОНУС!"
            else:
                header = "✅ Бонус получен!"

            next_day = (streak % 7) + 1
            next_amt = BONUS_AMOUNTS.get(next_day, 10)

            text = (
                header + "\n"
                "━━━━━━━━━━━━━━━\n\n"
                "💎 Начислено: +" + str(crystals) + " кристаллов!\n\n"
                "📅 Стрик: День " + str(streak) + " из 7\n"
                + bar + "\n\n"
                "⏳ Следующий бонус через 24 часа\n"
                "💎 Завтра: +" + str(next_amt) + " кристаллов\n\n"
                "Не пропускай — стрик сбросится! 🔥"
            )
        else:
            hours_left = result["hours_until_next"]
            streak     = result["streak"]
            h  = int(hours_left)
            mn = int((hours_left - h) * 60)
            bar = _build_streak_bar(min(streak, 7))

            next_day = (streak % 7) + 1
            next_amt = BONUS_AMOUNTS.get(next_day, 10)

            text = (
                "⏳ Бонус уже получен сегодня\n"
                "━━━━━━━━━━━━━━━\n\n"
                "📅 Стрик: День " + str(streak) + " из 7\n"
                + bar + "\n\n"
                "🕐 Следующий через: " + str(h) + " ч " + str(mn) + " мин\n"
                "💎 Завтра: +" + str(next_amt) + " кристаллов\n\n"
                "Возвращайся завтра! 🔥"
            )

        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=back_kb
            )
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=back_kb)
