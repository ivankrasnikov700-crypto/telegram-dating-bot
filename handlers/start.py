# handlers/start.py
# Обработчик команды /start — приветственное сообщение с фото

from keyboards.inline import get_main_menu
from database import register_user, is_banned, get_user, get_usd_balance
from database.chat_sessions import get_model_active_chats
from database.settings import get_setting
from utils.notify import notify_channel

WELCOME_TEXT = (
    "👑 Miss Moldova — Private Club\n\n"
    "Ты только что открыл дверь в закрытый мир\n"
    "где красота Молдовы без фильтров и границ 🌹\n\n"
    "Здесь собраны самые яркие, смелые и желанные\n"
    "девушки страны — и они сами выбирают\n"
    "что показать своим избранным 🔥\n\n"
    "💎 Это не просто бот — это клуб для тех\n"
    "кто ценит настоящую красоту\n\n"
    "━━━━━━━━━━━━━━━\n"
    "🔥 Что тебя ждёт внутри:\n"
    "• 📸 Эксклюзивные фото и видео моделей Miss Moldova\n"
    "• 👑 Контент который нигде больше не найдёшь\n"
    "• 🚀 Новинки каждую неделю\n"
    "• 💬 Личное общение с моделями\n"
    "━━━━━━━━━━━━━━━\n\n"
    "🔒 Доступ только по Premium подписке\n"
    "Бесплатно — лишь превью того что внутри\n\n"
    "Готов войти в клуб избранных? 👇"
)


def register_start_handlers(bot):

    @bot.message_handler(commands=['start'])
    def start(message):
        user_id   = message.from_user.id
        username  = message.from_user.username or ""
        full_name = message.from_user.full_name or ""

        if is_banned(user_id):
            bot.send_message(user_id, "🚫 Ваш аккаунт заблокирован.")
            return

        register_user(user_id, username, full_name)

        user_ref = ("@" + username) if username else full_name

        user = get_user(user_id)
        if user and user.get("user_role") == "model":
            balance = round(float(get_usd_balance(user_id)), 2)
            try:
                chats = get_model_active_chats(user_id)
                chat_count = len(chats)
            except Exception:
                chat_count = 0
            first_name = message.from_user.first_name or "Модель"
            bot.send_message(
                message.chat.id,
                "👋 Привет, " + first_name + "!\n\n"
                "💰 Баланс: *$" + str(balance) + "*\n"
                "💬 Активных чатов: " + str(chat_count) + "\n\n"
                "Команды:\n"
                "/balance — проверить баланс\n"
                "/earnings — история заработка\n"
                "/withdraw — вывести средства\n\n"
                "Просто пиши сообщение — оно дойдёт до фаната.",
                parse_mode="Markdown"
            )
            return

        notify_channel(
            bot,
            "👤 Новый пользователь!\n"
            "━━━━━━━━━━━━━━━\n"
            "🏷 " + user_ref + "\n"
            "🆔 ID: " + str(user_id)
        )

        markup = get_main_menu()
        welcome_photo = get_setting("welcome_photo")

        if welcome_photo:
            try:
                bot.send_photo(
                    chat_id=message.chat.id,
                    photo=welcome_photo,
                    caption=WELCOME_TEXT,
                    reply_markup=markup
                )
                return
            except Exception as e:
                print("[START] Ошибка отправки фото: " + str(e))

        # Fallback — текстовое сообщение
        bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=markup)
