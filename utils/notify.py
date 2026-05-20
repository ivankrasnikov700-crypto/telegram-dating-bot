from config import ADMIN_CHANNEL_ID


def get_channel_id(bot=None) -> int:
    """Возвращает ID канала: из БД (приоритет) или из env."""
    try:
        from database.settings import get_setting
        stored = get_setting("admin_channel_id")
        if stored and str(stored).lstrip('-').isdigit():
            return int(stored)
    except Exception:
        pass
    return ADMIN_CHANNEL_ID


def notify_channel(bot, text: str):
    """Отправляет уведомление в admin-канал."""
    channel_id = get_channel_id(bot)
    if not channel_id:
        return
    try:
        bot.send_message(channel_id, text)
    except Exception as e:
        print("[CHANNEL NOTIFY ERROR] " + str(e))
