import time
from database import get_connection, _cur


def init_paid_media_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS paid_media (
            id             SERIAL PRIMARY KEY,
            model_user_id  BIGINT NOT NULL,
            fan_user_id    BIGINT NOT NULL,
            file_id        TEXT NOT NULL,
            file_type      TEXT DEFAULT 'photo',
            price_usd      REAL NOT NULL,
            preview_file_id TEXT,
            is_unlocked    INTEGER DEFAULT 0,
            created_at     BIGINT NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_paid_media_fan "
        "ON paid_media (fan_user_id, is_unlocked)"
    )
    conn.commit()
    conn.close()


def create_paid_media(model_user_id: int, fan_user_id: int,
                      file_id: str, file_type: str,
                      price_usd: float, preview_file_id: str = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO paid_media "
        "(model_user_id, fan_user_id, file_id, file_type, price_usd, preview_file_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (model_user_id, fan_user_id, file_id, file_type, price_usd, preview_file_id, int(time.time()))
    )
    media_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return media_id


def get_paid_media(media_id: int) -> dict | None:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute("SELECT * FROM paid_media WHERE id = %s", (media_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def unlock_and_pay(media_id: int, fan_id: int):
    """
    Atomically unlocks paid media for a fan.

    Returns:
        (True, row_dict)       — success
        (False, "reason_str")  — failure
    """
    conn = get_connection()
    cursor = _cur(conn)
    try:
        conn.autocommit = False

        cursor.execute(
            "SELECT * FROM paid_media WHERE id = %s AND fan_user_id = %s FOR UPDATE",
            (media_id, fan_id)
        )
        row = cursor.fetchone()
        if not row:
            return False, "not_found"
        row = dict(row)

        if row["is_unlocked"]:
            return False, "already_unlocked"

        price    = float(row["price_usd"])
        model_id = row["model_user_id"]

        cursor.execute(
            "SELECT balance_usd FROM users WHERE user_id = %s FOR UPDATE",
            (fan_id,)
        )
        fan_row = cursor.fetchone()
        if not fan_row or float(fan_row["balance_usd"]) < price:
            return False, "insufficient"

        model_share = round(price * 0.70, 2)
        now = int(time.time())

        cursor.execute(
            "UPDATE users SET balance_usd = balance_usd - %s WHERE user_id = %s",
            (price, fan_id)
        )
        cursor.execute(
            "UPDATE users SET balance_usd = balance_usd + %s WHERE user_id = %s",
            (model_share, model_id)
        )
        cursor.execute(
            "INSERT INTO balance_transactions (user_id, amount_usd, reason, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (fan_id, -price, "Paid media unlock #" + str(media_id), now)
        )
        cursor.execute(
            "INSERT INTO balance_transactions (user_id, amount_usd, reason, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (model_id, model_share, "Paid media sale #" + str(media_id), now)
        )
        cursor.execute(
            "UPDATE paid_media SET is_unlocked = 1 WHERE id = %s",
            (media_id,)
        )

        conn.commit()
        return True, row

    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()
