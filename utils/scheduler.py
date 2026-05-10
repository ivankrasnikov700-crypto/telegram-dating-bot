# utils/scheduler.py
# Фоновый планировщик — уведомления об истечении подписки
# Запускается в daemon-треде при старте бота
# Проверяет каждые 6 часов подписки которые истекают через 24 часа

import threading
import time
import logging

logger = logging.getLogger(__name__)


def start_scheduler(bot):
    """Запускает планировщик в фоновом daemon-треде"""
    thread = threading.Thread(
        target=_scheduler_loop,
        args=(bot,),
        daemon=True,  # Умрёт вместе с основным процессом
        name="SubscriptionScheduler"
    )
    thread.start()
    print("[SCHEDULER] Планировщик подписок запущен")


def _scheduler_loop(bot):
    """Основной цикл — проверка каждые 6 часов"""
    while True:
        try:
            _check_expiring_subscriptions(bot)
        except Exception as e:
            print("[SCHEDULER ERROR] " + str(e))
        # Ждём 6 часов перед следующей проверкой
        time.sleep(6 * 60 * 60)


def _check_expiring_subscriptions(bot):
    """
    Находит подписки которые истекают в ближайшие 24 часа.
    Шлёт уведомления пользователям (один раз на подписку).
    """
    from database import get_connection

    conn = get_connection()
    cursor = conn.cursor()

    now = int(time.time())
    in_24h = now + 24 * 3600  # через 24 часа

    # Ищем подписки которые истекают в ближайшие 24 часа
    # и по которым уведомление ещё не отправлялось
    cursor.execute('''
        SELECT user_id, subscription_type, subscription_expires
        FROM users
        WHERE subscription_expires IS NOT NULL
          AND subscription_expires BETWEEN ? AND ?
          AND subscription_notified = 0
    ''', (now, in_24h))

    expiring = cursor.fetchall()
    conn.close()

    if not expiring:
        print("[SCHEDULER] Истекающих подписок нет")
        return

    print("[SCHEDULER] Истекающих подписок: " + str(len(expiring)))

    for row in expiring:
        user_id = row[0]
        sub_type = row[1]
        expires_at = row[2]

        try:
            hours_left = max(1, (expires_at - now) // 3600)
            sub_name = "Fan" if "fan" in str(sub_type) else "Premium"

            from telebot import types
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton(
                    "🔄 Продлить " + sub_name,
                    callback_data="subscription"
                )
            )

            bot.send_message(
                user_id,
                "⏰ Подписка " + sub_name + " истекает через " + str(hours_left) + " ч!\n\n"
                "Не теряй доступ к Miss Moldova 💋\n"
                "Продли прямо сейчас — и получи новые кристаллы.",
                reply_markup=keyboard
            )

            # Помечаем как уведомлённого
            _mark_notified(user_id)
            print("[SCHEDULER] Уведомление → " + str(user_id))

        except Exception as e:
            print("[SCHEDULER] Ошибка для " + str(user_id) + ": " + str(e))


def _mark_notified(user_id: int):
    """Ставит флаг что уведомление уже отправлено"""
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET subscription_notified = 1 WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
    except Exception as e:
        print("[SCHEDULER] Ошибка mark_notified: " + str(e))
    finally:
        conn.close()


def add_scheduler_columns():
    """
    Добавляет колонку subscription_notified в таблицу users.
    Вызывается при старте — безопасная миграция.
    Сбрасывает флаг уведомления при продлении подписки.
    """
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN subscription_notified INTEGER DEFAULT 0"
        )
        conn.commit()
        print("[SCHEDULER] Миграция: добавлена колонка subscription_notified")
    except Exception:
        pass  # Колонка уже есть
    finally:
        conn.close()


def reset_notification_flag(user_id: int):
    """
    Сбрасывает флаг уведомления при активации новой подписки.
    Вызывать из database.activate_subscription() после обновления.
    """
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET subscription_notified = 0 WHERE user_id = ?",
            (user_id,)
        )
        conn.commit()
    except Exception as e:
        print("[SCHEDULER] Ошибка reset_flag: " + str(e))
    finally:
        conn.close()
