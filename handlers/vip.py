from telebot import types
from database import register_user
from database.settings import get_setting
from database.schedule import format_schedule_list


def register_vip_handlers(bot):

    @bot.callback_query_handler(func=lambda call: call.data == "vip_club")
    def vip_club_handler(call):
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        register_user(user_id, call.from_user.username or "", call.from_user.full_name or "")

        invite_link   = get_setting("vip_invite_link") or ""
        schedule_text = format_schedule_list()

        back_kb = types.InlineKeyboardMarkup(row_width=1)
        if invite_link:
            back_kb.add(
                types.InlineKeyboardButton("🚀 Войти в VIP Клуб", url=invite_link)
            )
        back_kb.add(
            types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu")
        )

        text = (
            "👑 VIP Клуб Miss Moldova\n"
            "━━━━━━━━━━━━━━━\n\n"
            "Добро пожаловать!\n\n"
            + schedule_text + "\n\n"
            "━━━━━━━━━━━━━━━\n"
            "💬 Модели отвечают на вопросы в канале\n"
            "🔔 Анонсы приходят за 1 час до сессии"
        )

        if not invite_link:
            text += "\n\n⚠️ Ссылка временно недоступна — обратись к администратору"

        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=back_kb
            )
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=back_kb)
