from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from db import connect_db


def create_leave_request(student_id: int, from_date: str, to_date: str, reason: str) -> int:
    reason = (reason or "").strip()[:500]
    if not reason:
        raise ValueError("Reason is required.")

    # Basic date validation (YYYY-MM-DD)
    try:
        f = date.fromisoformat(from_date)
        t = date.fromisoformat(to_date)
    except Exception:
        raise ValueError("Invalid date format.")
    if t < f:
        raise ValueError("To-date must be on/after from-date.")

    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO leave_requests (student_id, from_date, to_date, reason)
            VALUES (%s,%s,%s,%s)
            """,
            (student_id, str(f), str(t), reason),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        cur.close()
        conn.close()


def list_student_leave_requests(student_id: int, limit: int = 200) -> List[Dict]:
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT
              id,
              from_date,
              to_date,
              reason,
              status,
              DATE_FORMAT(created_at, '%Y-%m-%d %H:%i') AS created_at,
              DATE_FORMAT(decided_at, '%Y-%m-%d %H:%i') AS decided_at
            FROM leave_requests
            WHERE student_id=%s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (student_id, limit),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def list_teacher_pending_leaves(teacher_user_id: int, academic_year: int, limit: int = 300) -> List[Dict]:
    """
    Lists leave requests for students in the teacher's assigned class/section (latest assignment).
    """
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id FROM teachers WHERE user_id=%s", (teacher_user_id,))
        t = cur.fetchone()
        if not t:
            return []
        teacher_id = int(t["id"])

        cur.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s AND academic_year=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (teacher_id, academic_year),
        )
        a = cur.fetchone()
        if not a:
            return []

        class_no = int(a["class_no"])
        section = str(a["section"])
        table = f"class_{class_no:02d}_section_{'01' if section == 'A' else '02'}"

        cur.execute(
            f"""
            SELECT
              lr.id,
              lr.student_id,
              s.name AS student_name,
              u.phone AS student_phone,
              lr.from_date,
              lr.to_date,
              lr.reason,
              lr.status,
              DATE_FORMAT(lr.created_at, '%Y-%m-%d %H:%i') AS created_at
            FROM leave_requests lr
            JOIN students s ON s.id = lr.student_id
            JOIN users u ON u.id = s.user_id
            JOIN `{table}` ct ON ct.student_id = s.id
            WHERE lr.status='pending'
            ORDER BY lr.created_at DESC, lr.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def decide_leave_request(leave_id: int, status: str, decided_by_user_id: int) -> None:
    status = (status or "").strip().lower()
    if status not in {"approved", "rejected"}:
        raise ValueError("Invalid status.")

    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE leave_requests
            SET status=%s, decided_by_user_id=%s, decided_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (status, decided_by_user_id, int(leave_id)),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

