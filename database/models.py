import psycopg2
import psycopg2.extras
import time
from datetime import date
from database import get_connection


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def calculate_age(birth_date_str) -> int | None:
    if not birth_date_str:
        return None
    try:
        val = str(birth_date_str).strip()
        if '-' in val and len(val) == 10:
            birth = date.fromisoformat(val)
        elif '.' in val:
            day, month, year = val.split('.')
            birth = date(int(year), int(month), int(day))
        else:
            return None

        today = date.today()
        age = today.year - birth.year
        if (today.month, today.day) < (birth.month, birth.day):
            age -= 1
        return age
    except Exception as e:
        print("[DB] Ошибка вычисления возраста: " + str(e))
        return None


def _enrich_model(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    birth_date = d.get("birth_date")
    if birth_date:
        computed = calculate_age(birth_date)
        if computed is not None:
            d["age"] = computed
    return d


def init_models_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS models (
            id               SERIAL PRIMARY KEY,
            name             TEXT NOT NULL,
            age              INTEGER NOT NULL DEFAULT 0,
            birth_date       TEXT DEFAULT NULL,
            username         TEXT,
            description      TEXT,
            preview_photo    TEXT,
            telegram_user_id BIGINT DEFAULT NULL,
            is_active        INTEGER DEFAULT 1,
            created_at       BIGINT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_media (
            id SERIAL PRIMARY KEY,
            model_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            media_type TEXT DEFAULT 'photo',
            is_preview INTEGER DEFAULT 0,
            position INTEGER DEFAULT 0,
            created_at BIGINT,
            FOREIGN KEY (model_id) REFERENCES models(id)
        )
    ''')

    conn.commit()
    _migrate_add_birth_date(cursor, conn)
    _migrate_add_preview_photo_2(cursor, conn)
    conn.close()
    print("[DB] Таблицы моделей инициализированы")


def _migrate_add_birth_date(cursor, conn):
    try:
        cursor.execute(
            "ALTER TABLE models ADD COLUMN IF NOT EXISTS birth_date TEXT DEFAULT NULL"
        )
        conn.commit()
    except Exception as e:
        print("[DB] Миграция birth_date: " + str(e))


def _migrate_add_preview_photo_2(cursor, conn):
    try:
        cursor.execute(
            "ALTER TABLE models ADD COLUMN IF NOT EXISTS preview_photo_2 TEXT DEFAULT NULL"
        )
        conn.commit()
        print("[DB] Миграция: preview_photo_2 OK")
    except Exception as e:
        print("[DB] Миграция preview_photo_2: " + str(e))


def add_model(name: str, age_or_birthdate, username: str, description: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    birth_date = None
    age = 0
    val = str(age_or_birthdate).strip()
    if val.isdigit():
        age = int(val)
    else:
        birth_date = val
        computed = calculate_age(val)
        age = computed if computed is not None else 0

    cursor.execute('''
        INSERT INTO models (name, age, birth_date, username, description, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    ''', (name, age, birth_date, username or "", description, int(time.time())))

    model_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    print("[DB] Добавлена модель: " + name + " ID: " + str(model_id))
    return model_id


def get_all_models() -> list:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('''
        SELECT * FROM models WHERE is_active = 1
        ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [_enrich_model(row) for row in rows]


def get_model(model_id: int) -> dict | None:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('SELECT * FROM models WHERE id = %s', (model_id,))
    row = cursor.fetchone()
    conn.close()
    return _enrich_model(row)


def update_model(model_id: int, name: str = None, age_or_birthdate=None,
                 username: str = None, description: str = None):
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = %s")
        params.append(name.strip())

    if age_or_birthdate is not None:
        val = str(age_or_birthdate).strip()
        if val.isdigit():
            updates.append("age = %s")
            params.append(int(val))
        else:
            computed = calculate_age(val)
            updates.append("birth_date = %s")
            params.append(val)
            if computed:
                updates.append("age = %s")
                params.append(computed)

    if username is not None:
        updates.append("username = %s")
        params.append(username.strip())

    if description is not None:
        updates.append("description = %s")
        params.append(description.strip())

    if not updates:
        conn.close()
        return

    params.append(model_id)
    cursor.execute(
        "UPDATE models SET " + ", ".join(updates) + " WHERE id = %s",
        params
    )
    conn.commit()
    conn.close()
    print("[DB] Модель " + str(model_id) + " обновлена")


def add_model_media(model_id: int, file_id: str,
                    media_type: str = 'photo',
                    is_preview: int = 0,
                    position: int = 0):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO model_media (model_id, file_id, media_type, is_preview, position, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    ''', (model_id, file_id, media_type, is_preview, position, int(time.time())))
    conn.commit()
    conn.close()
    print("[DB] Медиа добавлено для модели " + str(model_id))


def get_preview_media(model_id: int) -> list:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('''
        SELECT * FROM model_media
        WHERE model_id = %s AND is_preview = 1
        ORDER BY position ASC
        LIMIT 3
    ''', (model_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_media(model_id: int) -> list:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('''
        SELECT * FROM model_media
        WHERE model_id = %s
        ORDER BY position ASC
    ''', (model_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def set_preview_photo(model_id: int, file_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE models SET preview_photo = %s WHERE id = %s', (file_id, model_id))
    conn.commit()
    conn.close()


def set_preview_photo_2(model_id: int, file_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE models SET preview_photo_2 = %s WHERE id = %s', (file_id, model_id))
    conn.commit()
    conn.close()


def link_model_telegram(model_id: int, telegram_user_id: int):
    """Link catalog model profile to a real Telegram user account."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE models SET telegram_user_id = %s WHERE id = %s",
        (telegram_user_id, model_id)
    )
    conn.commit()
    conn.close()
    print("[DB] Linked model #" + str(model_id) + " to Telegram user " + str(telegram_user_id))


def get_model_by_telegram_id(telegram_user_id: int) -> dict | None:
    """Find catalog model profile by linked Telegram user_id."""
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute(
        "SELECT * FROM models WHERE telegram_user_id = %s AND is_active = 1",
        (telegram_user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return _enrich_model(row) if row else None


def deactivate_model(model_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE models SET is_active = 0 WHERE id = %s
    ''', (model_id,))
    conn.commit()
    conn.close()
