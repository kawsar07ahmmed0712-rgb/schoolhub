from __future__ import annotations

from typing import Dict, List, Optional

from db import connect_db


def list_exams(academic_year: int) -> List[Dict]:
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT id, academic_year, name, DATE_FORMAT(created_at, '%Y-%m-%d %H:%i') AS created_at
            FROM exams
            WHERE academic_year=%s
            ORDER BY id DESC
            """,
            (academic_year,),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def create_exam(academic_year: int, name: str) -> int:
    name = (name or "").strip()[:60]
    if not name:
        raise ValueError("Exam name is required.")

    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO exams (academic_year, name)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE name=VALUES(name)
            """,
            (academic_year, name),
        )
        conn.commit()

        # Return the exam id (existing or new)
        cur.execute("SELECT id FROM exams WHERE academic_year=%s AND name=%s LIMIT 1", (academic_year, name))
        row = cur.fetchone()
        return int(row[0])
    finally:
        cur.close()
        conn.close()


def upsert_marks_bulk(
    exam_id: int,
    class_no: int,
    section: str,
    subject: str,
    max_marks: float,
    marks_by_student_id: Dict[int, float],
    entered_by_user_id: int,
) -> int:
    subject = (subject or "").strip()[:60]
    if not subject:
        raise ValueError("Subject is required.")
    section = (section or "").strip().upper()
    if section not in {"A", "B"}:
        raise ValueError("Invalid section.")
    if not (1 <= int(class_no) <= 10):
        raise ValueError("Invalid class.")
    if max_marks <= 0:
        raise ValueError("Max marks must be positive.")

    rows = []
    for student_id, mark in marks_by_student_id.items():
        if mark is None:
            continue
        try:
            mark_val = float(mark)
        except Exception:
            continue
        if mark_val < 0:
            mark_val = 0.0
        if mark_val > float(max_marks):
            mark_val = float(max_marks)
        rows.append((exam_id, class_no, section, int(student_id), subject, float(mark_val), float(max_marks), entered_by_user_id))

    if not rows:
        return 0

    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.executemany(
            """
            INSERT INTO marks
              (exam_id, class_no, section, student_id, subject, marks_obtained, max_marks, entered_by_user_id)
            VALUES
              (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              marks_obtained=VALUES(marks_obtained),
              max_marks=VALUES(max_marks),
              entered_by_user_id=VALUES(entered_by_user_id),
              entered_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        cur.close()
        conn.close()


def get_marks_for_class_exam(exam_id: int, class_no: int, section: str, subject: str) -> Dict[int, Dict]:
    section = (section or "").strip().upper()
    subject = (subject or "").strip()[:60]

    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT student_id, marks_obtained, max_marks
            FROM marks
            WHERE exam_id=%s AND class_no=%s AND section=%s AND subject=%s
            """,
            (exam_id, class_no, section, subject),
        )
        rows = cur.fetchall() or []
        out = {}
        for r in rows:
            out[int(r["student_id"])] = r
        return out
    finally:
        cur.close()
        conn.close()


def set_publication(exam_id: int, class_no: int, section: str, is_published: bool, published_by_user_id: int) -> None:
    section = (section or "").strip().upper()
    if section not in {"A", "B"}:
        raise ValueError("Invalid section.")
    if not (1 <= int(class_no) <= 10):
        raise ValueError("Invalid class.")

    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO exam_publications (exam_id, class_no, section, is_published, published_by_user_id)
            VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              is_published=VALUES(is_published),
              published_by_user_id=VALUES(published_by_user_id),
              published_at=CURRENT_TIMESTAMP
            """,
            (exam_id, class_no, section, 1 if is_published else 0, published_by_user_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def list_published_exams_for_student(student_id: int) -> List[Dict]:
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        # Find student's class/section through class tables (same logic as profile)
        found = None
        for class_no in range(1, 11):
            for section_letter, section_code in (("A", "01"), ("B", "02")):
                table = f"class_{class_no:02d}_section_{section_code}"
                cur.execute(f"SELECT 1 FROM `{table}` WHERE student_id=%s LIMIT 1", (student_id,))
                if cur.fetchone():
                    found = (class_no, section_letter)
                    break
            if found:
                break
        if not found:
            return []

        class_no, section = found
        cur.execute(
            """
            SELECT e.id, e.academic_year, e.name
            FROM exam_publications p
            JOIN exams e ON e.id = p.exam_id
            WHERE p.class_no=%s AND p.section=%s AND p.is_published=1
            ORDER BY e.academic_year DESC, e.id DESC
            """,
            (class_no, section),
        )
        return cur.fetchall() or []
    finally:
        cur.close()
        conn.close()


def get_student_result(exam_id: int, student_id: int) -> Dict:
    """
    Returns:
      {rows:[{subject, marks_obtained, max_marks}], total, max_total}
    Only returns rows if the exam is published for the student's class/section.
    """
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        # Determine class/section
        found = None
        for class_no in range(1, 11):
            for section_letter, section_code in (("A", "01"), ("B", "02")):
                table = f"class_{class_no:02d}_section_{section_code}"
                cur.execute(f"SELECT 1 FROM `{table}` WHERE student_id=%s LIMIT 1", (student_id,))
                if cur.fetchone():
                    found = (class_no, section_letter)
                    break
            if found:
                break
        if not found:
            return {"rows": [], "total": 0, "max_total": 0, "published": False}

        class_no, section = found
        cur.execute(
            """
            SELECT is_published
            FROM exam_publications
            WHERE exam_id=%s AND class_no=%s AND section=%s
            LIMIT 1
            """,
            (exam_id, class_no, section),
        )
        p = cur.fetchone()
        published = bool(p and int(p.get("is_published") or 0) == 1)
        if not published:
            return {"rows": [], "total": 0, "max_total": 0, "published": False}

        cur.execute(
            """
            SELECT subject, marks_obtained, max_marks
            FROM marks
            WHERE exam_id=%s AND student_id=%s
            ORDER BY subject ASC
            """,
            (exam_id, student_id),
        )
        rows = cur.fetchall() or []
        total = sum(float(r.get("marks_obtained") or 0) for r in rows)
        max_total = sum(float(r.get("max_marks") or 0) for r in rows)
        return {"rows": rows, "total": total, "max_total": max_total, "published": True}
    finally:
        cur.close()
        conn.close()

