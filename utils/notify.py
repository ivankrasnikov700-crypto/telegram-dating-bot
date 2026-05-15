from config import ADMIN_CHANNEL_ID


def notify_channel(bot, text: str):
    """Отправляет уведомление в admin-канал. Молча игнорирует ошибки."""
    if not ADMIN_CHANNEL_ID:
        return
    try:
        bot.send_message(ADMIN_CHANNEL_ID, text)
    except Exception as e:
        print("[CHANNEL NOTIFY ERROR] " + str(e))
