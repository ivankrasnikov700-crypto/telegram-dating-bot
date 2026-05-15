# handlers/start.py
# Обработчик команды /start — приветственное сообщение с фото

from keyboards.inline import get_main_menu
from database import register_user
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
        register_user(user_id, username, full_name)

        user_ref = ("@" + username) if username else full_name
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
