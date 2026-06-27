"""
Miss Moldova v2 — Database Migration Script
Run once: python database/migrate_v2.py

Removes crystal economy, adds real-money USD balance,
creates model_chats and balance_transactions tables.
"""

import sys
import os

# Make sure project root is on path when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DATABASE_URL
import psycopg2

STEPS = []

def step(label):
    def decorator(fn):
        STEPS.append((label, fn))
        return fn
    return decorator


@step("Drop crystal_transactions table")
def drop_crystal_transactions(cursor):
    cursor.execute("DROP TABLE IF EXISTS crystal_transactions")


@step("Remove crystals column from users")
def drop_crystals_column(cursor):
    cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS crystals")


@step("Remove crystals_added column from payments")
def drop_crystals_added(cursor):
    cursor.execute("ALTER TABLE payments DROP COLUMN IF EXISTS crystals_added")


@step("Add balance_usd column to users")
def add_balance_usd(cursor):
    cursor.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_usd REAL DEFAULT 0.0"
    )


@step("Add user_role column to users")
def add_user_role(cursor):
    cursor.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_role TEXT DEFAULT 'fan'"
    )


@step("Create balance_transactions table")
def create_balance_transactions(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS balance_transactions (
            id          SERIAL PRIMARY KEY,
            user_id     BIGINT NOT NULL,
            amount_usd  REAL NOT NULL,
            reason      TEXT NOT NULL,
            created_at  BIGINT NOT NULL
        )
    """)


@step("Create model_chats table")
def create_model_chats(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_chats (
            chat_id    TEXT PRIMARY KEY,
            fan_id     BIGINT NOT NULL,
            model_id   BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            is_active  INTEGER DEFAULT 1,
            created_at BIGINT NOT NULL
        )
    """)


@step("Add warnings_count column to users")
def add_warnings_count(cursor):
    cursor.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS warnings_count INTEGER DEFAULT 0"
    )


@step("Create index on model_chats(model_id, is_active)")
def create_model_chats_index(cursor):
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_chats_model "
        "ON model_chats (model_id, is_active)"
    )


@step("Create index on model_chats(fan_id, is_active)")
def create_model_chats_fan_index(cursor):
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_chats_fan "
        "ON model_chats (fan_id, is_active)"
    )


@step("Drop last_bonus_at column from users")
def drop_last_bonus_at(cursor):
    cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_bonus_at")


@step("Drop bonus_streak column from users")
def drop_bonus_streak(cursor):
    cursor.execute("ALTER TABLE users DROP COLUMN IF EXISTS bonus_streak")


@step("Add telegram_user_id column to models (links catalog to Telegram account)")
def add_telegram_user_id_to_models(cursor):
    cursor.execute(
        "ALTER TABLE models ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT DEFAULT NULL"
    )


@step("Create index on models(telegram_user_id)")
def create_models_tg_uid_index(cursor):
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_models_tg_uid ON models(telegram_user_id)"
    )


@step("Create model_withdrawals table")
def create_model_withdrawals(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_withdrawals (
            id             SERIAL PRIMARY KEY,
            model_user_id  BIGINT NOT NULL,
            amount_usd     REAL NOT NULL,
            ltc_address    TEXT NOT NULL,
            status         TEXT DEFAULT 'pending',
            notes          TEXT,
            created_at     BIGINT,
            processed_at   BIGINT
        )
    """)


def run_migration():
    print("=" * 55)
    print("  Miss Moldova v2 — Database Migration")
    print("=" * 55)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cursor = conn.cursor()

    errors = []
    for label, fn in STEPS:
        try:
            fn(cursor)
            conn.commit()
            print("  ✅ " + label)
        except Exception as e:
            conn.rollback()
            print("  ❌ " + label + ": " + str(e))
            errors.append((label, e))

    cursor.close()
    conn.close()

    print("=" * 55)
    if errors:
        print("Migration completed WITH ERRORS (" + str(len(errors)) + " failed)")
        for label, e in errors:
            print("  • " + label + ": " + str(e))
        sys.exit(1)
    else:
        print("Migration completed successfully (" + str(len(STEPS)) + " steps)")


if __name__ == "__main__":
    run_migration()
