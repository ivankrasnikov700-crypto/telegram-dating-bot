import psycopg2
import psycopg2.extras
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
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            crystals INTEGER DEFAULT 0,
            subscription_type TEXT DEFAULT NULL,
            subscription_expires BIGINT DEFAULT NULL,
            subscription_notified INTEGER DEFAULT 0,
            profiles_viewed INTEGER DEFAULT 0,
            favorites_count INTEGER DEFAULT 0,
            gifts_sent INTEGER DEFAULT 0,
            created_at BIGINT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            payment_id TEXT NOT NULL,
            sub_type TEXT NOT NULL,
            amount_ltc REAL NOT NULL,
            amount_usd REAL NOT NULL,
            crystals_added INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at BIGINT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS crystal_transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at BIGINT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

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


def add_crystals(user_id: int, amount: int, reason: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET crystals = crystals + %s
        WHERE user_id = %s
    ''', (amount, user_id))
    cursor.execute('''
        INSERT INTO crystal_transactions (user_id, amount, reason, created_at)
        VALUES (%s, %s, %s, %s)
    ''', (user_id, amount, reason, int(time.time())))
    conn.commit()
    conn.close()


def spend_crystals(user_id: int, amount: int, reason: str) -> bool:
    user = get_user(user_id)
    if not user or user["crystals"] < amount:
        return False

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET crystals = crystals - %s
        WHERE user_id = %s
    ''', (amount, user_id))
    cursor.execute('''
        INSERT INTO crystal_transactions (user_id, amount, reason, created_at)
        VALUES (%s, %s, %s, %s)
    ''', (user_id, -amount, reason, int(time.time())))
    conn.commit()
    conn.close()
    return True


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
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned INTEGER DEFAULT 0")
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
                 amount_ltc: float, amount_usd: float, crystals: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments
        (user_id, payment_id, sub_type, amount_ltc, amount_usd, crystals_added, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    ''', (user_id, payment_id, sub_type, amount_ltc, amount_usd, crystals, int(time.time())))
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


def get_days_since_registration(user_id: int) -> int:
    user = get_user(user_id)
    if not user:
        return 0
    created_at = user.get("created_at") or int(time.time())
    return (int(time.time()) - int(created_at)) // 86400
