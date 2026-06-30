import psycopg2
import psycopg2.extras
import json
import time
from config import DATABASE_URL


def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id              BIGINT PRIMARY KEY,
            username             TEXT,
            full_name            TEXT,
            balance_usd          REAL DEFAULT 0.0,
            user_role            TEXT DEFAULT 'fan',
            is_banned            INTEGER DEFAULT 0,
            subscription_type    TEXT DEFAULT NULL,
            subscription_expires BIGINT DEFAULT NULL,
            subscription_notified INTEGER DEFAULT 0,
            profiles_viewed      INTEGER DEFAULT 0,
            favorites_count      INTEGER DEFAULT 0,
            gifts_sent           INTEGER DEFAULT 0,
            warnings_count       INTEGER DEFAULT 0,
            created_at           BIGINT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id         SERIAL PRIMARY KEY,
            user_id    BIGINT NOT NULL,
            payment_id TEXT NOT NULL,
            sub_type   TEXT NOT NULL,
            amount_ltc REAL NOT NULL,
            amount_usd REAL NOT NULL,
            status     TEXT DEFAULT 'pending',
            created_at BIGINT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS balance_transactions (
            id         SERIAL PRIMARY KEY,
            user_id    BIGINT NOT NULL,
            amount_usd REAL NOT NULL,
            reason     TEXT NOT NULL,
            created_at BIGINT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_chats (
            chat_id    TEXT PRIMARY KEY,
            fan_id     BIGINT NOT NULL,
            model_id   BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            is_active  INTEGER DEFAULT 1,
            created_at BIGINT NOT NULL
        )
    ''')

    # Pending LTC payments — survives bot restarts
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_payments (
            user_id      BIGINT PRIMARY KEY,
            chat_id      BIGINT NOT NULL,
            invoice_json TEXT NOT NULL,
            created_at   BIGINT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cryptobot_invoices (
            invoice_id   BIGINT PRIMARY KEY,
            user_id      BIGINT NOT NULL,
            amount_usd   REAL NOT NULL,
            credited     BOOLEAN DEFAULT FALSE,
            created_at   BIGINT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id          SERIAL PRIMARY KEY,
            chat_id     TEXT NOT NULL,
            sender_id   BIGINT NOT NULL,
            sender_role TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  BIGINT NOT NULL
        )
    ''')
    cursor.execute(
        'CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id, created_at)'
    )

    # Добавляем колонки, которые могли отсутствовать в ранних версиях БД
    for col, definition in [
        ("balance_usd",  "REAL DEFAULT 0.0"),
        ("user_role",    "TEXT DEFAULT 'fan'"),
        ("is_banned",    "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}")
        except Exception:
            conn.rollback()

    conn.commit()
    conn.close()
    print("[DB] База данных инициализирована (PostgreSQL)")


def register_user(user_id: int, username: str, full_name: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_id, username, full_name, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
    ''', (user_id, username, full_name, int(time.time())))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> dict | None:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def activate_subscription(user_id: int, sub_type: str, days: int, crystals: int, minutes: int = 0):
    if minutes > 0:
        expires_at = int(time.time()) + (minutes * 60)
        print("[DB] Тестовая подписка: " + str(minutes) + " мин для user " + str(user_id))
    else:
        expires_at = int(time.time()) + (days * 86400)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET subscription_type = %s,
            subscription_expires = %s,
            subscription_notified = 0,
            crystals = crystals + %s
        WHERE user_id = %s
    ''', (sub_type, expires_at, crystals, user_id))

    cursor.execute('''
        INSERT INTO crystal_transactions (user_id, amount, reason, created_at)
        VALUES (%s, %s, %s, %s)
    ''', (user_id, crystals, "Подписка " + sub_type, int(time.time())))

    conn.commit()
    conn.close()
    print("[DB] Подписка активирована для user " + str(user_id) +
          " истекает в " + str(expires_at))


def add_usd_balance(user_id: int, amount: float, reason: str):
    """Credits USD to user balance and logs in balance_transactions."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET balance_usd = balance_usd + %s WHERE user_id = %s",
        (amount, user_id)
    )
    cursor.execute(
        "INSERT INTO balance_transactions (user_id, amount_usd, reason, created_at) "
        "VALUES (%s, %s, %s, %s)",
        (user_id, amount, reason, int(time.time()))
    )
    conn.commit()
    conn.close()


def get_usd_balance(user_id: int) -> float:
    """Returns current USD balance for user."""
    user = get_user(user_id)
    return float(user.get("balance_usd", 0.0)) if user else 0.0


def get_all_user_ids() -> list:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_user_by_username(username: str) -> dict | None:
    username = username.lstrip("@").lower()
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute("SELECT * FROM users WHERE LOWER(username) = %s", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def ban_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()


def unban_user(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()


def is_banned(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return bool(user.get("is_banned", 0))


def check_subscription(user_id: int) -> dict:
    user = get_user(user_id)

    if not user:
        return {"active": False, "type": None, "days_left": 0}

    expires = user.get("subscription_expires")
    sub_type = user.get("subscription_type")

    if not expires or not sub_type:
        return {"active": False, "type": None, "days_left": 0}

    now = int(time.time())

    if now > int(expires):
        cancel_subscription(user_id)
        return {"active": False, "type": None, "days_left": 0}

    days_left = max(0, (int(expires) - now) // 86400)
    seconds_left = int(expires) - now

    return {
        "active":       True,
        "type":         sub_type,
        "days_left":    days_left,
        "seconds_left": seconds_left,
        "expires_at":   int(expires)
    }


def cancel_subscription(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET subscription_type = NULL,
            subscription_expires = NULL
        WHERE user_id = %s
    ''', (user_id,))
    conn.commit()
    conn.close()
    print("[DB] Подписка отменена для user " + str(user_id))


def save_payment(user_id: int, payment_id: str, sub_type: str,
                 amount_ltc: float, amount_usd: float, crystals: int = 0):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO payments (user_id, payment_id, sub_type, amount_ltc, amount_usd, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, payment_id, sub_type, amount_ltc, amount_usd, int(time.time()))
    )
    conn.commit()
    conn.close()


def confirm_payment(payment_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE payments SET status = 'confirmed'
        WHERE payment_id = %s
    ''', (payment_id,))
    conn.commit()
    conn.close()


def increment_warning(user_id: int) -> int:
    """Atomically increments warnings_count and returns the new value."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET warnings_count = warnings_count + 1 "
        "WHERE user_id = %s RETURNING warnings_count",
        (user_id,)
    )
    new_count = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return new_count


def get_days_since_registration(user_id: int) -> int:
    user = get_user(user_id)
    if not user:
        return 0
    created_at = user.get("created_at") or int(time.time())
    return (int(time.time()) - int(created_at)) // 86400


# ─────────────────────────────────────────────
# Pending payments — persist across restarts
# ─────────────────────────────────────────────

def save_pending_payment(user_id: int, chat_id: int, invoice: dict):
    """Saves invoice to DB so monitoring can resume after bot restart."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO pending_payments (user_id, chat_id, invoice_json, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE
            SET chat_id = EXCLUDED.chat_id,
                invoice_json = EXCLUDED.invoice_json,
                created_at = EXCLUDED.created_at
    ''', (user_id, chat_id, json.dumps(invoice), int(time.time())))
    conn.commit()
    conn.close()


def load_all_pending_payments() -> list:
    """Returns all pending payments that haven't expired yet."""
    now = int(time.time())
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute(
        "SELECT user_id, chat_id, invoice_json FROM pending_payments WHERE created_at > %s",
        (now - 3600,)
    )
    rows = cursor.fetchall()
    conn.close()
    result = []
    for row in rows:
        try:
            invoice = json.loads(row["invoice_json"])
            # Skip if invoice already expired
            if invoice.get("expires_at", 0) > now:
                result.append({
                    "user_id": row["user_id"],
                    "chat_id": row["chat_id"],
                    "invoice": invoice,
                })
        except Exception:
            pass
    return result


def delete_pending_payment(user_id: int):
    """Removes a pending payment after it's confirmed or expired."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pending_payments WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
