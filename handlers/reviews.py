from telebot import types
from database.reviews import get_reviews, count_reviews


def register_reviews_handlers(bot):

    @bot.callback_query_handler(func=lambda call: call.data == "reviews")
    def show_reviews(call):
        bot.answer_callback_query(call.id)
        _send_reviews_page(bot, call.message.chat.id, page=0,
                           message_id=call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("reviews_page_"))
    def reviews_page(call):
        bot.answer_callback_query(call.id)
        page = int(call.data.replace("reviews_page_", ""))
        _send_reviews_page(bot, call.message.chat.id, page=page)


def _send_reviews_page(bot, chat_id: int, page: int, message_id: int = None):
    reviews = get_reviews()

    if not reviews:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("« Назад", callback_data="back_to_menu"))
        try:
            bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text="⭐ Отзывов пока нет\n\nСкоро здесь появятся впечатления наших участников 💫",
                reply_markup=keyboard
            )
        except Exception:
            bot.send_message(chat_id,
                "⭐ Отзывов пока нет\n\nСкоро здесь появятся впечатления наших участников 💫",
                reply_markup=keyboard)
        return

    total = len(reviews)
    page = max(0, min(page, total - 1))
    review = reviews[page]

    nav = types.InlineKeyboardMarkup(row_width=3)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(
            "◀️", callback_data="reviews_page_" + str(page - 1)
        ))
    nav_buttons.append(types.InlineKeyboardButton(
        str(page + 1) + "/" + str(total), callback_data="noop"
    ))
    if page < total - 1:
        nav_buttons.append(types.InlineKeyboardButton(
            "▶️", callback_data="reviews_page_" + str(page + 1)
        ))
    nav.row(*nav_buttons)
    nav.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_menu"))

    caption = (review.get("caption") or "") + (
        "\n\n⭐ " + str(page + 1) + " из " + str(total)
    )

    # Удаляем старое сообщение и отправляем фото
    if message_id:
        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

    try:
        bot.send_photo(
            chat_id=chat_id,
            photo=review["file_id"],
            caption=caption,
            reply_markup=nav
        )
    except Exception as e:
        print("[REVIEWS] " + str(e))
