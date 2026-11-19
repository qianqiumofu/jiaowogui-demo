"""归返聚合锁；所有写入按学生×业务夜串行，再锁预约、码（技术路线）。"""
from datetime import date
from sqlalchemy import text
from sqlalchemy.engine import Connection

def lock_night(conn: Connection, student_id: str, service_date: date) -> None:
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                 {"key": f"return:{student_id}:{service_date.isoformat()}"})
