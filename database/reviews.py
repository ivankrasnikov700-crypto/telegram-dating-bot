import time
import psycopg2.extras
from database import get_connection


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def init_reviews_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            file_id TEXT NOT NULL,
            caption TEXT DEFAULT NULL,
            created_at BIGINT
        )
    ''')
    conn.commit()
    conn.close()
    print("[DB] Таблица отзывов инициализирована")


def add_review(file_id: str, caption: str = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO reviews (file_id, caption, created_at)
        VALUES (%s, %s, %s)
        RETURNING id
    ''', (file_id, caption, int(time.time())))
    review_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return review_id


def get_reviews() -> list:
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('SELECT * FROM reviews ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_review(review_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reviews WHERE id = %s', (review_id,))
    conn.commit()
    conn.close()


def count_reviews() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM reviews')
    n = cursor.fetchone()[0]
    conn.close()
    return n
