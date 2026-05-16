import time
import psycopg2.extras
from database import get_connection, add_crystals

BONUS_AMOUNTS = {1: 3, 2: 5, 3: 7, 4: 10, 5: 10, 6: 10, 7: 30}


def init_bonus_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_at BIGINT DEFAULT 0"
    )
    cursor.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_streak INTEGER DEFAULT 0"
    )
    conn.commit()
    conn.close()
    print("[DB] Бонус: миграция выполнена")


def get_bonus_info(user_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT last_bonus_at, bonus_streak FROM users WHERE user_id = %s",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"last_bonus_at": 0, "bonus_streak": 0}
    return {
        "last_bonus_at": row["last_bonus_at"] or 0,
        "bonus_streak":  row["bonus_streak"]  or 0
    }


def claim_daily_bonus(user_id: int) -> dict:
    """
    Пытается выдать ежедневный бонус.
    Возвращает:
        success=True  → crystals, streak, is_week_complete
        success=False → hours_until_next, streak
    """
    now    = int(time.time())
    info   = get_bonus_info(user_id)
    last   = info["last_bonus_at"]
    streak = info["bonus_streak"]
    elapsed = now - last

    if last > 0 and elapsed < 86400:
        hours_left = (86400 - elapsed) / 3600
        return {
            "success":          False,
            "hours_until_next": hours_left,
            "streak":           streak
        }

    if elapsed >= 172800 or streak == 0:
        new_streak = 1
    elif streak >= 7:
        new_streak = 1
    else:
        new_streak = streak + 1

    crystals = BONUS_AMOUNTS.get(new_streak, 10)
    is_week_complete = (streak == 7 and new_streak == 1)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET last_bonus_at = %s, bonus_streak = %s WHERE user_id = %s",
        (now, new_streak, user_id)
    )
    conn.commit()
    conn.close()

    add_crystals(user_id, crystals, "Ежедневный бонус день " + str(new_streak))

    return {
        "success":          True,
        "crystals":         crystals,
        "streak":           new_streak,
        "is_week_complete": is_week_complete
    }
