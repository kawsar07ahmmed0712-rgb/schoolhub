from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional


def class_table_name(class_no: int, section_letter: str) -> str:
    section_letter = (section_letter or "").strip().upper()
    section_code = "01" if section_letter == "A" else "02"
    return f"class_{int(class_no):02d}_section_{section_code}"


def find_student_class_section(cur: Any, student_id: int) -> Optional[Dict[str, Any]]:
    """
    Returns: {"class_no": int, "section": "A"|"B", "roll": int}
    """
    student_id = int(student_id)
    for class_no in range(1, 11):
        for section_letter in ("A", "B"):
            table = class_table_name(class_no, section_letter)
            cur.execute(f"SELECT roll FROM `{table}` WHERE student_id=%s LIMIT 1", (student_id,))
            row = cur.fetchone()
            if row:
                roll_val = row["roll"] if isinstance(row, dict) else row[0]
                return {"class_no": int(class_no), "section": str(section_letter), "roll": int(roll_val)}
    return None


def get_class_teacher_for(cur: Any, class_no: int, section: str, academic_year: int) -> Optional[Dict[str, Any]]:
    section = (section or "").strip().upper()
    cur.execute(
        """
        SELECT
          t.id AS teacher_id,
          t.name AS teacher_name,
          t.teacher_code,
          u.phone AS teacher_phone
        FROM class_teacher_assignments a
        JOIN teachers t ON t.id = a.teacher_id
        JOIN users u ON u.id = t.user_id
        WHERE a.class_no=%s AND a.section=%s AND a.academic_year=%s
        LIMIT 1
        """,
        (int(class_no), section, int(academic_year)),
    )
    return cur.fetchone()


def get_schedule_teachers_for_class_day(cur: Any, class_no: int, section: str, weekday: str) -> Dict[int, Dict[str, Any]]:
    """
    Returns map: {period_no: {"teacher_name": str, "teacher_phone": str}}
    """
    weekday = (weekday or "").strip().lower()
    section = (section or "").strip().upper()
    cur.execute(
        """
        SELECT
          s.period_no,
          t.name AS teacher_name,
          u.phone AS teacher_phone
        FROM teacher_schedule_slots s
        JOIN teachers t ON t.id = s.teacher_id
        JOIN users u ON u.id = t.user_id
        WHERE s.class_no=%s AND s.section=%s AND s.weekday=%s
        ORDER BY s.period_no ASC
        """,
        (int(class_no), section, weekday),
    )
    out: Dict[int, Dict[str, Any]] = {}
    for r in cur.fetchall() or []:
        out[int(r["period_no"])] = {"teacher_name": r.get("teacher_name") or "-", "teacher_phone": r.get("teacher_phone") or "-"}
    return out


def parse_iso_date(s: str) -> date:
    return date.fromisoformat((s or "").strip())

