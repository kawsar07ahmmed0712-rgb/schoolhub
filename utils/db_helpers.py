from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator, Tuple

from db import connect_db


@contextmanager
def db_cursor(dictionary: bool = True) -> Generator[Tuple[Any, Any], None, None]:
    """
    Context manager that yields (conn, cursor) and always closes them.
    """
    conn = connect_db()
    cur = conn.cursor(dictionary=dictionary)
    try:
        yield conn, cur
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def get_student_id_by_user_id(user_id: int) -> int | None:
    with db_cursor(dictionary=True) as (_conn, cur):
        cur.execute("SELECT id FROM students WHERE user_id=%s", (int(user_id),))
        row = cur.fetchone()
        return int(row["id"]) if row else None


def get_teacher_id_by_user_id(user_id: int) -> int | None:
    with db_cursor(dictionary=True) as (_conn, cur):
        cur.execute("SELECT id FROM teachers WHERE user_id=%s", (int(user_id),))
        row = cur.fetchone()
        return int(row["id"]) if row else None

