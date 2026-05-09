# database/__init__.py
# База данных SQLite — пользователи, подписки, кристаллы

import sqlite3
import os
import time
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Создаёт подключение к базе данных"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Инициализация базы данных — создаём таблицы"""
    conn = get_connection()
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            crystals INTEGER DEFAULT 0,
            subscription_type TEXT DEFAULT NULL,
            subscription_expires INTEGER DEFAULT NULL,
            profiles_viewed INTEGER DEFAULT 0,
            favorites_count INTEGER DEFAULT 0,
            gifts_sent INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    ''')

    # Таблица платежей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            payment_id TEXT NOT NULL,
            sub_type TEXT NOT NULL,
            amount_ltc REAL NOT NULL,
            amount_usd REAL NOT NULL,
            crystals_added INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    # Таблица транзакций кристаллов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS crystal_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    conn.commit()
    conn.close()
    print("[DB] База данных инициализирована")


def register_user(user_id: int, username: str, full_name: str):
    """Регистрирует нового пользователя если его нет"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
    ''', (user_id, username, full_name))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> dict | None:
    """Возвращает данные пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def activate_subscription(user_id: int, sub_type: str, days: int, crystals: int):
    """Активирует подписку и начисляет кристаллы"""
    expires_at = int(time.time()) + (days * 86400)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET subscription_type = ?,
            subscription_expires = ?,
            crystals = crystals + ?
        WHERE user_id = ?
    ''', (sub_type, expires_at, crystals, user_id))
    cursor.execute('''
        INSERT INTO crystal_transactions (user_id, amount, reason)
        VALUES (?, ?, ?)
    ''', (user_id, crystals, "Подписка " + sub_type))
    conn.commit()
    conn.close()
    print("[DB] Подписка активирована для user " + str(user_id))


def add_crystals(user_id: int, amount: int, reason: str):
    """Начисляет кристаллы пользователю"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET crystals = crystals + ?
        WHERE user_id = ?
    ''', (amount, user_id))
    cursor.execute('''
        INSERT INTO crystal_transactions (user_id, amount, reason)
        VALUES (?, ?, ?)
    ''', (user_id, amount, reason))
    conn.commit()
    conn.close()


def spend_crystals(user_id: int, amount: int, reason: str) -> bool:
    """Списывает кристаллы — возвращает False если недостаточно"""
    user = get_user(user_id)
    if not user or user["crystals"] < amount:
        return False

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users SET crystals = crystals - ?
        WHERE user_id = ?
    ''', (amount, user_id))
    cursor.execute('''
        INSERT INTO crystal_transactions (user_id, amount, reason)
        VALUES (?, ?, ?)
    ''', (user_id, -amount, reason))
    conn.commit()
    conn.close()
    return True


def check_subscription(user_id: int) -> dict:
    """Проверяет активность подписки"""
    user = get_user(user_id)

    if not user:
        return {"active": False, "type": None, "days_left": 0}

    expires = user.get("subscription_expires")
    sub_type = user.get("subscription_type")

    if not expires or not sub_type:
        return {"active": False, "type": None, "days_left": 0}

    now = int(time.time())

    if now > expires:
        cancel_subscription(user_id)
        return {"active": False, "type": None, "days_left": 0}

    days_left = (expires - now) // 86400
    return {"active": True, "type": sub_type, "days_left": days_left}


def cancel_subscription(user_id: int):
    """Отменяет подписку пользователя"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users
        SET subscription_type = NULL,
            subscription_expires = NULL
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()


def save_payment(user_id: int, payment_id: str, sub_type: str,
                 amount_ltc: float, amount_usd: float, crystals: int):
    """Сохраняет информацию о платеже"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO payments
        (user_id, payment_id, sub_type, amount_ltc, amount_usd, crystals_added)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, payment_id, sub_type, amount_ltc, amount_usd, crystals))
    conn.commit()
    conn.close()


def confirm_payment(payment_id: str):
    """Помечает платёж как подтверждённый"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE payments SET status = 'confirmed'
        WHERE payment_id = ?
    ''', (payment_id,))
    conn.commit()
    conn.close()


def get_days_since_registration(user_id: int) -> int:
    """Возвращает количество дней с регистрации"""
    user = get_user(user_id)
    if not user:
        return 0
    created_at = user.get("created_at", int(time.time()))
    return (int(time.time()) - created_at) // 86400