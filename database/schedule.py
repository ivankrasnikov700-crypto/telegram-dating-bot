import time
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from database import get_connection

CHISINAU = timezone(timedelta(hours=3))

DAY_MAP = {
    "ПН": 0, "ВТ": 1, "СР": 2, "ЧТ": 3,
    "ПТ": 4, "СБ": 5, "ВС": 6
}
DAY_NAMES = {v: k for k, v in DAY_MAP.items()}


def init_schedule_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id SERIAL PRIMARY KEY,
            model_name TEXT NOT NULL,
            days TEXT NOT NULL,
            session_time TEXT NOT NULL,
            last_announced_at BIGINT DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at BIGINT
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Расписание: таблица инициализирована")


def add_schedule(model_name: str, days: str, session_time: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO schedules (model_name, days, session_time, created_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, (model_name, days.upper().strip(), session_time.strip(), int(time.time())))
    schedule_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return schedule_id


def get_all_schedules() -> list:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT * FROM schedules WHERE is_active = 1 ORDER BY session_time"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_schedule(schedule_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE schedules SET is_active = 0 WHERE id = %s", (schedule_id,)
    )
    conn.commit()
    conn.close()


def mark_announced(schedule_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE schedules SET last_announced_at = %s WHERE id = %s",
        (int(time.time()), schedule_id)
    )
    conn.commit()
    conn.close()


def _next_occurrence(day_nums: list, h: int, m: int) -> datetime | None:
    """Возвращает ближайшее следующее время сессии по Кишинёву."""
    now = datetime.now(CHISINAU)
    for offset in range(8):
        candidate = now + timedelta(days=offset)
        session   = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate.weekday() in day_nums and session > now:
            return session
    return None


def get_upcoming_sessions(after_minutes: int = 55, within_minutes: int = 65) -> list:
    """
    Возвращает сессии, которые начнутся через [after_minutes, within_minutes].
    Пропускает уже объявлённые (last_announced_at < 12 часов назад).
    """
    now       = datetime.now(CHISINAU)
    now_ts    = int(now.timestamp())
    schedules = get_all_schedules()
    result    = []

    for sched in schedules:
        days_list = [d.strip() for d in sched["days"].split(",")]
        day_nums  = [DAY_MAP[d] for d in days_list if d in DAY_MAP]
        if not day_nums:
            continue

        try:
            h, m = map(int, sched["session_time"].split(":"))
        except Exception:
            continue

        next_dt = _next_occurrence(day_nums, h, m)
        if next_dt is None:
            continue

        diff_min = (next_dt - now).total_seconds() / 60
        if not (after_minutes <= diff_min <= within_minutes):
            continue

        last_ann = sched.get("last_announced_at") or 0
        if now_ts - last_ann < 12 * 3600:
            continue

        result.append({
            **sched,
            "minutes_until":    int(diff_min),
            "session_datetime": next_dt
        })

    return result


def format_schedule_list() -> str:
    """Форматирует расписание для отображения пользователям."""
    schedules = get_all_schedules()
    if not schedules:
        return "📅 Расписание пока не добавлено"

    lines = ["📅 Расписание сессий:\n━━━━━━━━━━━━━━━"]
    for s in schedules:
        lines.append(
            "💃 " + s["model_name"] + "\n"
            "   📆 " + s["days"] + "  ⏰ " + s["session_time"]
        )
    return "\n\n".join(lines)
