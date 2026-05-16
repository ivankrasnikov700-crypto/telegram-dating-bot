# utils/scheduler.py
# Фоновый планировщик:
#   1. Каждые 6 часов — уведомления об истекающих подписках
#   2. Каждый день в 10:00 Кишинёв (UTC+3) — статистика в admin-канал
#   3. Каждые 2 минуты — анонсы сессий моделей в VIP-канал

import threading
import time
import datetime
import logging

logger = logging.getLogger(__name__)

# Час отправки статистики по местному времени (UTC+3, Кишинёв)
_STATS_HOUR_LOCAL = 10
_UTC_OFFSET_HOURS = 3


def start_scheduler(bot):
    """Запускает три фоновых треда: подписки, статистика, анонсы сессий."""
    threading.Thread(
        target=_subscription_loop,
        args=(bot,),
        daemon=True,
        name="SubscriptionChecker"
    ).start()

    threading.Thread(
        target=_daily_stats_loop,
        args=(bot,),
        daemon=True,
        name="DailyStats"
    ).start()

    threading.Thread(
        target=_session_announcement_loop,
        args=(bot,),
        daemon=True,
        name="SessionAnnouncer"
    ).start()

    print("[SCHEDULER] Запущен. Статистика каждый день в "
          + str(_STATS_HOUR_LOCAL) + ":00 по Кишинёву (UTC+"
          + str(_UTC_OFFSET_HOURS) + ")")


# ─────────────────────────────────────────────
# Проверка истекающих подписок (каждые 6 часов)
# ─────────────────────────────────────────────

def _subscription_loop(bot):
    while True:
        try:
            _check_expiring_subscriptions(bot)
        except Exception as e:
            print("[SCHEDULER ERROR] " + str(e))
        time.sleep(6 * 60 * 60)


def _check_expiring_subscriptions(bot):
    """Находит подписки которые истекают в ближайшие 24 часа и уведомляет."""
    import psycopg2.extras
    from database import get_connection

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    now = int(time.time())
    in_24h = now + 24 * 3600

    cursor.execute('''
        SELECT user_id, subscription_type, subscription_expires
        FROM users
        WHERE subscription_expires IS NOT NULL
          AND subscription_expires BETWEEN %s AND %s
          AND subscription_notified = 0
    ''', (now, in_24h))

    expiring = cursor.fetchall()
    conn.close()

    if not expiring:
        print("[SCHEDULER] Истекающих подписок нет")
        return

    print("[SCHEDULER] Истекающих подписок: " + str(len(expiring)))

    for row in expiring:
        user_id  = row["user_id"]
        sub_type = row["subscription_type"]
        expires  = row["subscription_expires"]

        try:
            hours_left = max(1, (expires - now) // 3600)
            sub_name   = "Fan" if "fan" in str(sub_type) else "Premium"

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
                "⏰ Подписка " + sub_name + " истекает через "
                + str(hours_left) + " ч!\n\n"
                "Не теряй доступ к Miss Moldova 💋\n"
                "Продли прямо сейчас — и получи новые кристаллы.",
                reply_markup=keyboard
            )

            _mark_notified(user_id)
            print("[SCHEDULER] Уведомление → " + str(user_id))

        except Exception as e:
            print("[SCHEDULER] Ошибка для " + str(user_id) + ": " + str(e))


def _mark_notified(user_id: int):
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET subscription_notified = 1 WHERE user_id = %s",
            (user_id,)
        )
        conn.commit()
    except Exception as e:
        print("[SCHEDULER] Ошибка mark_notified: " + str(e))
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Ежедневная статистика в 10:00 Кишинёв
# ─────────────────────────────────────────────

def _daily_stats_loop(bot):
    """Ждёт следующего 10:00 по Кишинёву, отправляет статистику, повторяет."""
    while True:
        _sleep_until_stats_time()
        try:
            _send_daily_stats(bot)
        except Exception as e:
            print("[STATS ERROR] " + str(e))
        # Небольшая пауза чтобы не сработало дважды в одну минуту
        time.sleep(90)


def _sleep_until_stats_time():
    """Спит ровно до следующего 10:00 по Кишинёву (UTC+3)."""
    now_utc  = datetime.datetime.utcnow()
    now_local = now_utc + datetime.timedelta(hours=_UTC_OFFSET_HOURS)

    target = now_local.replace(
        hour=_STATS_HOUR_LOCAL, minute=0, second=0, microsecond=0
    )
    if now_local >= target:
        target += datetime.timedelta(days=1)

    secs = (target - now_local).total_seconds()
    print("[STATS] Следующая отправка через "
          + str(int(secs // 3600)) + " ч "
          + str(int((secs % 3600) // 60)) + " мин")
    time.sleep(secs)


def _send_daily_stats(bot):
    """Собирает статистику из БД и отправляет в admin-канал."""
    from config import ADMIN_CHANNEL_ID
    if not ADMIN_CHANNEL_ID:
        return

    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()

    now_ts = int(time.time())

    # Всего пользователей
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    # Активные подписки
    cursor.execute(
        "SELECT COUNT(*) FROM users "
        "WHERE subscription_type IS NOT NULL AND subscription_expires > %s",
        (now_ts,)
    )
    active_subs = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM users "
        "WHERE subscription_type LIKE 'fan%%' AND subscription_expires > %s",
        (now_ts,)
    )
    fan_count = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM users "
        "WHERE subscription_type LIKE 'premium%%' AND subscription_expires > %s",
        (now_ts,)
    )
    premium_count = cursor.fetchone()[0]

    # Платежи
    cursor.execute(
        "SELECT COUNT(*) FROM payments WHERE status = 'confirmed'"
    )
    total_payments = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COALESCE(SUM(amount_usd), 0) FROM payments WHERE status = 'confirmed'"
    )
    total_usd = round(cursor.fetchone()[0], 2)

    # За последние 24 часа
    since_24h = now_ts - 86400
    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE created_at > %s",
        (since_24h,)
    )
    new_users_24h = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COALESCE(SUM(amount_usd), 0) FROM payments "
        "WHERE status = 'confirmed' AND created_at > %s",
        (since_24h,)
    )
    usd_24h = round(cursor.fetchone()[0], 2)

    # Активных моделей
    cursor.execute("SELECT COUNT(*) FROM models WHERE is_active = 1")
    models_count = cursor.fetchone()[0]

    conn.close()

    now_local = datetime.datetime.utcnow() + datetime.timedelta(hours=_UTC_OFFSET_HOURS)
    date_str  = now_local.strftime("%d.%m.%Y")

    text = (
        "📊 Ежедневная статистика Miss Moldova\n"
        "━━━━━━━━━━━━━━━\n"
        "📅 " + date_str + " | 10:00 Кишинёв\n\n"

        "👥 Пользователи:\n"
        "  Всего: " + str(total_users) + "\n"
        "  Новых за 24 ч: +" + str(new_users_24h) + "\n\n"

        "💎 Подписки:\n"
        "  Активных: " + str(active_subs) + "\n"
        "  🌸 Fan: " + str(fan_count) + "\n"
        "  👑 Premium: " + str(premium_count) + "\n\n"

        "💰 Финансы:\n"
        "  Всего платежей: " + str(total_payments) + "\n"
        "  Выручка всего: $" + str(total_usd) + "\n"
        "  За 24 ч: $" + str(usd_24h) + "\n\n"

        "👩 Активных моделей: " + str(models_count) + "\n"
        "━━━━━━━━━━━━━━━"
    )

    try:
        bot.send_message(ADMIN_CHANNEL_ID, text)
        print("[STATS] Статистика отправлена в канал")
    except Exception as e:
        print("[STATS] Ошибка отправки: " + str(e))


# ─────────────────────────────────────────────
# Миграция БД
# ─────────────────────────────────────────────

def add_scheduler_columns():
    """Добавляет колонку subscription_notified если её нет."""
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_notified INTEGER DEFAULT 0"
        )
        conn.commit()
        print("[SCHEDULER] Миграция: subscription_notified OK")
    except Exception as e:
        print("[SCHEDULER] Миграция: " + str(e))
    finally:
        conn.close()


def reset_notification_flag(user_id: int):
    """Сбрасывает флаг уведомления при активации новой подписки."""
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET subscription_notified = 0 WHERE user_id = %s",
            (user_id,)
        )
        conn.commit()
    except Exception as e:
        print("[SCHEDULER] Ошибка reset_flag: " + str(e))
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Анонсы VIP-сессий (каждые 2 минуты)
# ─────────────────────────────────────────────

def _session_announcement_loop(bot):
    """Проверяет расписание каждые 2 минуты и публикует анонсы за ~1 час."""
    while True:
        try:
            _check_and_announce_sessions(bot)
        except Exception as e:
            print("[SESSION ANNOUNCER ERROR] " + str(e))
        time.sleep(2 * 60)


def _check_and_announce_sessions(bot):
    from config import VIP_CHANNEL_ID
    from database.schedule import get_upcoming_sessions, mark_announced

    if not VIP_CHANNEL_ID:
        return

    sessions = get_upcoming_sessions(after_minutes=55, within_minutes=65)
    if not sessions:
        return

    for session in sessions:
        model_name = session["model_name"]
        minutes    = session["minutes_until"]
        sess_dt    = session["session_datetime"]
        time_str   = sess_dt.strftime("%H:%M")

        text = (
            "👑 VIP Анонс Miss Moldova\n"
            "━━━━━━━━━━━━━━━\n\n"
            "💃 Через " + str(minutes) + " минут в сети:\n"
            "   " + model_name + "\n\n"
            "⏰ Начало сессии в " + time_str + "\n"
            "💬 Задавай вопросы — она ответит!\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🔔 Будь онлайн!"
        )

        try:
            bot.send_message(VIP_CHANNEL_ID, text)
            mark_announced(session["id"])
            print("[SESSION] Анонс отправлен: " + model_name + " в " + time_str)
        except Exception as e:
            print("[SESSION] Ошибка отправки анонса: " + str(e))
