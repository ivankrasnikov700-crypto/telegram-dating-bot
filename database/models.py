# database/models.py
# Работа с моделями — добавление, получение, управление контентом
# Исправлено:
# 1. Добавлено поле birth_date — возраст вычисляется динамически
# 2. age при получении модели считается на лету из birth_date
# 3. Обратная совместимость — старые записи с числовым age работают
# 4. Добавлена update_model() для редактирования профиля через бота

import sqlite3
from datetime import date
from database import get_connection


# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def calculate_age(birth_date_str) -> int | None:
    """
    Вычисляет актуальный возраст из даты рождения.
    Поддерживает форматы: '1998-05-15' и '15.05.1998'

    Returns:
        int: возраст в годах, или None если дата не задана
    """
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
        # Если день рождения ещё не наступил в этом году
        if (today.month, today.day) < (birth.month, birth.day):
            age -= 1
        return age
    except Exception as e:
        print("[DB] Ошибка вычисления возраста: " + str(e))
        return None


def _enrich_model(row) -> dict | None:
    """
    Конвертирует Row модели в dict, динамически вычисляя возраст.
    Если есть birth_date — считаем из неё, иначе берём статичное age.
    """
    if row is None:
        return None
    d = dict(row)
    birth_date = d.get("birth_date")
    if birth_date:
        computed = calculate_age(birth_date)
        if computed is not None:
            d["age"] = computed  # Перезаписываем статичный возраст актуальным
    return d


# ─────────────────────────────────────────────
# Инициализация таблиц
# ─────────────────────────────────────────────

def init_models_db():
    """Создаём таблицы для моделей и медиа"""
    conn = get_connection()
    cursor = conn.cursor()

    # Таблица моделей — добавлено поле birth_date
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL DEFAULT 0,
            birth_date TEXT DEFAULT NULL,
            username TEXT,
            description TEXT,
            preview_photo TEXT,
            is_active INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    ''')

    # Таблица медиа моделей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            media_type TEXT DEFAULT 'photo',
            is_preview INTEGER DEFAULT 0,
            position INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (model_id) REFERENCES models(id)
        )
    ''')

    conn.commit()

    # Миграция: добавляем birth_date к существующим таблицам если нет
    _migrate_add_birth_date(cursor, conn)

    conn.close()
    print("[DB] Таблицы моделей инициализированы")


def _migrate_add_birth_date(cursor, conn):
    """Безопасно добавляет колонку birth_date если её нет (для старых БД)"""
    try:
        cursor.execute("ALTER TABLE models ADD COLUMN birth_date TEXT DEFAULT NULL")
        conn.commit()
        print("[DB] Миграция: добавлена колонка birth_date")
    except Exception:
        pass  # Колонка уже существует — нормально


# ─────────────────────────────────────────────
# CRUD модели
# ─────────────────────────────────────────────

def add_model(name: str, age_or_birthdate, username: str, description: str) -> int:
    """
    Добавляет новую модель в базу данных.

    Args:
        age_or_birthdate: возраст числом (24) или дата "ДД.ММ.ГГГГ" / "ГГГГ-ММ-ДД"

    Returns:
        int: id новой модели
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Определяем — передали возраст или дату рождения
    birth_date = None
    age = 0

    val = str(age_or_birthdate).strip()
    if val.isdigit():
        # Передали просто возраст числом — дату рождения не знаем
        age = int(val)
        birth_date = None
    else:
        # Передали дату рождения — вычисляем возраст
        birth_date = val
        computed = calculate_age(val)
        age = computed if computed is not None else 0

    cursor.execute('''
        INSERT INTO models (name, age, birth_date, username, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, age, birth_date, username, description))

    model_id = cursor.lastrowid
    conn.commit()
    conn.close()
    print("[DB] Добавлена модель: " + name + " ID: " + str(model_id))
    return model_id


def get_all_models() -> list:
    """Возвращает список всех активных моделей с динамическим возрастом"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM models WHERE is_active = 1
        ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    # Динамически вычисляем возраст для каждой модели
    return [_enrich_model(row) for row in rows]


def get_model(model_id: int) -> dict | None:
    """Возвращает данные модели по ID с динамическим возрастом"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM models WHERE id = ?', (model_id,))
    row = cursor.fetchone()
    conn.close()
    return _enrich_model(row)


def update_model(model_id: int, name: str = None, age_or_birthdate=None,
                 username: str = None, description: str = None):
    """
    Обновляет данные модели (редактирование профиля через бота).
    Передавай только те поля которые нужно обновить.
    """
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name.strip())

    if age_or_birthdate is not None:
        val = str(age_or_birthdate).strip()
        if val.isdigit():
            updates.append("age = ?")
            params.append(int(val))
        else:
            # Дата рождения
            computed = calculate_age(val)
            updates.append("birth_date = ?")
            params.append(val)
            if computed:
                updates.append("age = ?")
                params.append(computed)

    if username is not None:
        updates.append("username = ?")
        params.append(username.strip())

    if description is not None:
        updates.append("description = ?")
        params.append(description.strip())

    if not updates:
        conn.close()
        return

    params.append(model_id)
    cursor.execute(
        "UPDATE models SET " + ", ".join(updates) + " WHERE id = ?",
        params
    )
    conn.commit()
    conn.close()
    print("[DB] Модель " + str(model_id) + " обновлена")


# ─────────────────────────────────────────────
# Медиа
# ─────────────────────────────────────────────

def add_model_media(model_id: int, file_id: str,
                    media_type: str = 'photo',
                    is_preview: int = 0,
                    position: int = 0):
    """
    Добавляет медиафайл к модели.

    Args:
        model_id:   ID модели
        file_id:    file_id из Telegram
        media_type: photo или video
        is_preview: 1 если это превью (для Fan)
        position:   порядковый номер
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO model_media (model_id, file_id, media_type, is_preview, position)
        VALUES (?, ?, ?, ?, ?)
    ''', (model_id, file_id, media_type, is_preview, position))
    conn.commit()
    conn.close()
    print("[DB] Медиа добавлено для модели " + str(model_id))


def get_preview_media(model_id: int) -> list:
    """Возвращает превью медиа (3 фото) для Fan подписки"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM model_media
        WHERE model_id = ? AND is_preview = 1
        ORDER BY position ASC
        LIMIT 3
    ''', (model_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_media(model_id: int) -> list:
    """Возвращает всё медиа модели для Premium подписки"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM model_media
        WHERE model_id = ?
        ORDER BY position ASC
    ''', (model_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def set_preview_photo(model_id: int, file_id: str):
    """Устанавливает главное фото профиля модели"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE models SET preview_photo = ?
        WHERE id = ?
    ''', (file_id, model_id))
    conn.commit()
    conn.close()


def deactivate_model(model_id: int):
    """Деактивирует модель (скрывает из каталога)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE models SET is_active = 0
        WHERE id = ?
    ''', (model_id,))
    conn.commit()
    conn.close()
