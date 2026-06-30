# database/withdrawals.py
# Withdrawal requests for models — request, approve, reject, history

import time
from database import get_connection, _cur, add_usd_balance

MIN_WITHDRAWAL_USD = 10.0


def init_withdrawals_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_withdrawals (
            id             SERIAL PRIMARY KEY,
            model_user_id  BIGINT NOT NULL,
            amount_usd     REAL NOT NULL,
            ltc_address    TEXT,
            asset          TEXT DEFAULT 'USDT',
            status         TEXT DEFAULT 'pending',
            notes          TEXT,
            created_at     BIGINT,
            processed_at   BIGINT
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_mw_status "
        "ON model_withdrawals (status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_mw_model "
        "ON model_withdrawals (model_user_id)"
    )
    # Migrate existing table: make ltc_address nullable and add asset column
    try:
        cursor.execute(
            "ALTER TABLE model_withdrawals ALTER COLUMN ltc_address DROP NOT NULL"
        )
    except Exception:
        pass
    try:
        cursor.execute(
            "ALTER TABLE model_withdrawals ADD COLUMN IF NOT EXISTS asset TEXT DEFAULT 'USDT'"
        )
    except Exception:
        pass
    conn.commit()
    conn.close()
    print("[DB] model_withdrawals table ready")


def request_withdrawal(model_user_id: int, amount_usd: float,
                       ltc_address: str = None, asset: str = "USDT") -> int:
    """Creates a withdrawal request and immediately freezes the balance.
    Raises ValueError if insufficient balance. Returns the new request id."""
    amount_usd = round(amount_usd, 2)
    conn = get_connection()
    cursor = _cur(conn)
    try:
        conn.autocommit = False

        cursor.execute(
            "SELECT balance_usd FROM users WHERE user_id = %s FOR UPDATE",
            (model_user_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("User not found")

        balance = float(row["balance_usd"])
        if balance < amount_usd:
            raise ValueError(
                "Insufficient balance: $" + str(round(balance, 2)) +
                " < $" + str(amount_usd)
            )

        cursor.execute(
            "UPDATE users SET balance_usd = balance_usd - %s WHERE user_id = %s",
            (amount_usd, model_user_id)
        )
        cursor.execute(
            "INSERT INTO balance_transactions (user_id, amount_usd, reason, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (model_user_id, -amount_usd, "Заморозка вывода (pending)", int(time.time()))
        )
        cursor.execute('''
            INSERT INTO model_withdrawals
                (model_user_id, amount_usd, ltc_address, asset, status, created_at)
            VALUES (%s, %s, %s, %s, 'pending', %s)
            RETURNING id
        ''', (model_user_id, amount_usd,
              ltc_address.strip() if ltc_address else None,
              asset, int(time.time())))
        new_id = cursor.fetchone()["id"]
        conn.commit()
        return new_id

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending_withdrawals() -> list:
    """All pending withdrawal requests, newest first."""
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('''
        SELECT mw.*, u.username, u.full_name
        FROM model_withdrawals mw
        LEFT JOIN users u ON u.user_id = mw.model_user_id
        WHERE mw.status = 'pending'
        ORDER BY mw.created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_model_withdrawals(model_user_id: int) -> list:
    """Withdrawal history for a specific model (newest first)."""
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute('''
        SELECT * FROM model_withdrawals
        WHERE model_user_id = %s
        ORDER BY created_at DESC
        LIMIT 20
    ''', (model_user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_withdrawal(request_id: int) -> dict | None:
    """Single withdrawal request by ID."""
    conn = get_connection()
    cursor = _cur(conn)
    cursor.execute(
        "SELECT * FROM model_withdrawals WHERE id = %s",
        (request_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def process_withdrawal(request_id: int, new_status: str, notes: str = "") -> dict | None:
    """
    Updates withdrawal status atomically (only if still 'pending').
    - paid:     balance already frozen at request time — nothing to deduct
    - rejected: returns frozen amount back to model's balance
    Returns updated record, or None if already processed (race protection).
    """
    w = get_withdrawal(request_id)
    if not w:
        return None

    conn = get_connection()
    cursor = conn.cursor()
    try:
        conn.autocommit = False

        cursor.execute('''
            UPDATE model_withdrawals
            SET status = %s, notes = %s, processed_at = %s
            WHERE id = %s AND status = 'pending'
        ''', (new_status, notes, int(time.time()), request_id))

        if cursor.rowcount == 0:
            conn.rollback()
            return None

        if new_status == "rejected":
            cursor.execute(
                "UPDATE users SET balance_usd = balance_usd + %s WHERE user_id = %s",
                (w["amount_usd"], w["model_user_id"])
            )
            cursor.execute(
                "INSERT INTO balance_transactions "
                "(user_id, amount_usd, reason, created_at) VALUES (%s, %s, %s, %s)",
                (w["model_user_id"], w["amount_usd"],
                 "Возврат отклонённого вывода #" + str(request_id), int(time.time()))
            )

        conn.commit()
        w["status"] = new_status
        w["notes"]  = notes
        return w

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
