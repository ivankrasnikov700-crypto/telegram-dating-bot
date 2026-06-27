import time
from database import get_connection, _cur

CHAT_PRICE_USD = 5.0
MODEL_SHARE    = 0.70   # 70% модели
PLATFORM_SHARE = 0.30   # 30% платформе


class InsufficientBalanceError(Exception):
    pass


class ActiveChatExistsError(Exception):
    pass


def activate_day_chat(fan_id: int, model_id: int) -> dict:
    """
    Atomically purchases 24-hour unlimited chat access for fan→model.

    1. Locks fan row (FOR UPDATE) and checks balance >= $5
    2. Deducts $5 from fan, credits $3.50 to model
    3. Logs both sides in balance_transactions
    4. Creates model_chats record valid for 86400 seconds

    Raises:
        InsufficientBalanceError: fan balance < CHAT_PRICE_USD
        ActiveChatExistsError:    non-expired session already exists
    """
    now        = int(time.time())
    expires_at = now + 86400
    chat_id    = str(fan_id) + "_" + str(model_id)
    model_earn = round(CHAT_PRICE_USD * MODEL_SHARE, 2)

    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Lock fan row to prevent race conditions
        cursor.execute(
            "SELECT balance_usd FROM users WHERE user_id = %s FOR UPDATE",
            (fan_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("Fan user_id " + str(fan_id) + " not found")

        fan_balance = float(row[0])
        if fan_balance < CHAT_PRICE_USD:
            raise InsufficientBalanceError(
                "Insufficient balance: $" + str(round(fan_balance, 2)) +
                " < $" + str(CHAT_PRICE_USD)
            )

        # Check for existing active session
        cursor.execute(
            "SELECT chat_id FROM model_chats "
            "WHERE chat_id = %s AND is_active = 1 AND expires_at > %s",
            (chat_id, now)
        )
        if cursor.fetchone():
            raise ActiveChatExistsError("Active chat session already exists")

        # Deduct from fan
        cursor.execute(
            "UPDATE users SET balance_usd = balance_usd - %s WHERE user_id = %s",
            (CHAT_PRICE_USD, fan_id)
        )

        # Credit model share
        cursor.execute(
            "UPDATE users SET balance_usd = balance_usd + %s WHERE user_id = %s",
            (model_earn, model_id)
        )

        # Audit log — fan debit
        cursor.execute(
            "INSERT INTO balance_transactions (user_id, amount_usd, reason, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (fan_id, -CHAT_PRICE_USD, "Chat 24h with model " + str(model_id), now)
        )

        # Audit log — model credit
        cursor.execute(
            "INSERT INTO balance_transactions (user_id, amount_usd, reason, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (model_id, model_earn, "Chat earnings from fan " + str(fan_id), now)
        )

        # Create chat session
        cursor.execute(
            "INSERT INTO model_chats (chat_id, fan_id, model_id, expires_at, is_active, created_at) "
            "VALUES (%s, %s, %s, %s, 1, %s) "
            "ON CONFLICT (chat_id) DO UPDATE "
            "SET expires_at = EXCLUDED.expires_at, is_active = 1, created_at = EXCLUDED.created_at",
            (chat_id, fan_id, model_id, expires_at, now)
        )

        conn.commit()
        print("[CHAT] Activated 24h session " + chat_id +
              " fan=$-" + str(CHAT_PRICE_USD) + " model=$+" + str(model_earn))

        return {
            "chat_id":       chat_id,
            "fan_id":        fan_id,
            "model_id":      model_id,
            "expires_at":    expires_at,
            "price_usd":     CHAT_PRICE_USD,
            "model_share":   model_earn,
            "platform_share": round(CHAT_PRICE_USD * PLATFORM_SHARE, 2),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_active_chat(fan_id: int, model_id: int) -> dict | None:
    """Returns active chat session between fan and model, or None."""
    now     = int(time.time())
    chat_id = str(fan_id) + "_" + str(model_id)
    conn    = get_connection()
    cursor  = _cur(conn)
    cursor.execute(
        "SELECT * FROM model_chats "
        "WHERE chat_id = %s AND is_active = 1 AND expires_at > %s",
        (chat_id, now)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_model_active_chats(model_id: int) -> list:
    """Returns all active chat sessions for a model (for message routing)."""
    now    = int(time.time())
    conn   = get_connection()
    cursor = _cur(conn)
    cursor.execute(
        "SELECT * FROM model_chats "
        "WHERE model_id = %s AND is_active = 1 AND expires_at > %s "
        "ORDER BY expires_at ASC",
        (model_id, now)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fan_active_chats(fan_id: int) -> list:
    """Returns all active chat sessions for a fan."""
    now    = int(time.time())
    conn   = get_connection()
    cursor = _cur(conn)
    cursor.execute(
        "SELECT * FROM model_chats "
        "WHERE fan_id = %s AND is_active = 1 AND expires_at > %s "
        "ORDER BY expires_at ASC",
        (fan_id, now)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_chat(chat_id: str):
    """Manually deactivates a chat session (e.g. on fraud ban)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE model_chats SET is_active = 0 WHERE chat_id = %s",
        (chat_id,)
    )
    conn.commit()
    conn.close()


def deactivate_all_model_chats(model_id: int) -> int:
    """Deactivates all active chat sessions for a model (used on 3rd-strike ban)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE model_chats SET is_active = 0 "
        "WHERE model_id = %s AND is_active = 1",
        (model_id,)
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def expire_old_chats():
    """Marks expired sessions as inactive. Call from scheduler every 10 min."""
    now  = int(time.time())
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE model_chats SET is_active = 0 "
        "WHERE expires_at < %s AND is_active = 1",
        (now,)
    )
    expired = cursor.rowcount
    conn.commit()
    conn.close()
    if expired:
        print("[CHAT] Expired " + str(expired) + " chat session(s)")
