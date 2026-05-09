# database/models.py
# Работа с моделями — добавление, получение, управление контентом

import sqlite3
from database import get_connection


def init_models_db():
    """Создаём таблицы для моделей"""
    conn = get_connection()
    cursor = conn.cursor()

    # Таблица моделей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
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
    conn.close()
    print("[DB] Таблицы моделей инициализированы")


def add_model(name: str, age: int, username: str, description: str) -> int:
    """
    Добавляет новую модель в базу данных.

    Returns:
        int: id новой модели
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO models (name, age, username, description)
        VALUES (?, ?, ?, ?)
    ''', (name, age, username, description))
    model_id = cursor.lastrowid
    conn.commit()
    conn.close()
    print("[DB] Добавлена модель: " + name + " ID: " + str(model_id))
    return model_id


def get_all_models() -> list:
    """Возвращает список всех активных моделей"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM models WHERE is_active = 1
        ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_model(model_id: int) -> dict | None:
    """Возвращает данные модели по ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM models WHERE id = ?', (model_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def add_model_media(model_id: int, file_id: str,
                    media_type: str = 'photo',
                    is_preview: int = 0,
                    position: int = 0):
    """
    Добавляет медиафайл к модели.

    Args:
        model_id: ID модели
        file_id: file_id из Telegram
        media_type: photo или video
        is_preview: 1 если это превью (для Fan)
        position: порядковый номер
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
    """
    Возвращает превью медиа (3 фото) для Fan подписки.
    """
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
    """
    Возвращает всё медиа модели для Premium подписки.
    """
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
    """Деактивирует модель"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE models SET is_active = 0
        WHERE id = ?
    ''', (model_id,))
    conn.commit()
    conn.close()
