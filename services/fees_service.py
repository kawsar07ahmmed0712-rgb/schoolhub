from db import connect_db

def create_fee_plan(class_no: int, section: str, academic_year: int, fee_month: int, amount: int) -> int:
  if section not in {"A", "B"}:
    raise ValueError("Invalid section.")
  if not (1 <= class_no <= 10):
    raise ValueError("Invalid class.")
  if not (1 <= fee_month <= 12):
    raise ValueError("Invalid month.")
  if amount <= 0:
    raise ValueError("Amount must be positive.")

  conn = connect_db()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO fee_plans (class_no, section, academic_year, fee_month, amount)
      VALUES (%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE amount=VALUES(amount)
      """,
      (class_no, section, academic_year, fee_month, amount),
    )
    conn.commit()
    return cur.lastrowid
  finally:
    cur.close()
    conn.close()

def list_fee_plans_for_class(class_no: int, section: str, academic_year: int):
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT id, fee_month, amount
      FROM fee_plans
      WHERE class_no=%s AND section=%s AND academic_year=%s
      ORDER BY fee_month ASC
      """,
      (class_no, section, academic_year),
    )
    return cur.fetchall() or []
  finally:
    cur.close()
    conn.close()

def get_student_id_by_phone(phone: str):
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT s.id AS student_id
      FROM users u
      JOIN students s ON s.user_id = u.id
      WHERE u.phone=%s AND u.role='student'
      """,
      (phone,),
    )
    row = cur.fetchone()
    return row["student_id"] if row else None
  finally:
    cur.close()
    conn.close()

def record_payment(fee_plan_id: int, student_id: int, paid_amount: int, received_by_user_id: int, note: str = "") -> int:
  if paid_amount <= 0:
    raise ValueError("Paid amount must be positive.")

  conn = connect_db()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO fee_payments (fee_plan_id, student_id, paid_amount, received_by_user_id, note)
      VALUES (%s,%s,%s,%s,%s)
      """,
      (fee_plan_id, student_id, paid_amount, received_by_user_id, (note or "").strip()[:255]),
    )
    conn.commit()
    return cur.lastrowid
  finally:
    cur.close()
    conn.close()

def get_fee_status_for_student(student_id: int, class_no: int, section: str, academic_year: int):
  """
  Returns rows like:
  [{fee_month, amount, paid_total, due}]
  """
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT
        p.fee_month,
        p.amount,
        COALESCE(SUM(pay.paid_amount), 0) AS paid_total,
        (p.amount - COALESCE(SUM(pay.paid_amount), 0)) AS due
      FROM fee_plans p
      LEFT JOIN fee_payments pay
        ON pay.fee_plan_id = p.id
        AND pay.student_id = %s
      WHERE p.class_no=%s AND p.section=%s AND p.academic_year=%s
      GROUP BY p.id
      ORDER BY p.fee_month ASC
      """,
      (student_id, class_no, section, academic_year),
    )
    return cur.fetchall() or []
  finally:
    cur.close()
    conn.close()



from typing import Optional, List, Dict

def list_payments_admin(
  limit: int = 200,
  class_no: Optional[int] = None,
  section: Optional[str] = None,
  academic_year: Optional[int] = None,
  fee_month: Optional[int] = None,
  student_phone: Optional[str] = None,
):
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    sql = """
      SELECT
        pay.id,
        pay.paid_amount,
        DATE_FORMAT(pay.paid_at, '%Y-%m-%d %H:%i') AS paid_at,
        pay.note,
        p.class_no, p.section, p.academic_year, p.fee_month, p.amount AS plan_amount,
        u.phone AS student_phone,
        ru.phone AS received_by_phone
      FROM fee_payments pay
      JOIN fee_plans p ON p.id = pay.fee_plan_id
      JOIN students s ON s.id = pay.student_id
      JOIN users u ON u.id = s.user_id
      JOIN users ru ON ru.id = pay.received_by_user_id
      WHERE 1=1
    """
    params = []

    if class_no is not None:
      sql += " AND p.class_no=%s"
      params.append(class_no)
    if section is not None and section in {"A", "B"}:
      sql += " AND p.section=%s"
      params.append(section)
    if academic_year is not None:
      sql += " AND p.academic_year=%s"
      params.append(academic_year)
    if fee_month is not None:
      sql += " AND p.fee_month=%s"
      params.append(fee_month)
    if student_phone:
      sql += " AND u.phone=%s"
      params.append(student_phone.strip())

    sql += " ORDER BY pay.paid_at DESC, pay.id DESC LIMIT %s"
    params.append(limit)

    cur.execute(sql, tuple(params))
    return cur.fetchall() or []
  finally:
    cur.close()
    conn.close()

def list_payments_for_student(student_id: int, limit: int = 200):
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT
        pay.id,
        pay.paid_amount,
        DATE_FORMAT(pay.paid_at, '%Y-%m-%d %H:%i') AS paid_at,
        pay.note,
        p.class_no, p.section, p.academic_year, p.fee_month, p.amount AS plan_amount,
        ru.phone AS received_by_phone
      FROM fee_payments pay
      JOIN fee_plans p ON p.id = pay.fee_plan_id
      JOIN users ru ON ru.id = pay.received_by_user_id
      WHERE pay.student_id=%s
      ORDER BY pay.paid_at DESC, pay.id DESC
      LIMIT %s
      """,
      (student_id, limit),
    )
    return cur.fetchall() or []
  finally:
    cur.close()
    conn.close()

def get_payment_receipt_admin(payment_id: int):
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT
        pay.id,
        pay.paid_amount,
        DATE_FORMAT(pay.paid_at, '%Y-%m-%d %H:%i') AS paid_at,
        pay.note,
        p.class_no, p.section, p.academic_year, p.fee_month, p.amount AS plan_amount,
        u.phone AS student_phone,
        ru.phone AS received_by_phone
      FROM fee_payments pay
      JOIN fee_plans p ON p.id = pay.fee_plan_id
      JOIN students s ON s.id = pay.student_id
      JOIN users u ON u.id = s.user_id
      JOIN users ru ON ru.id = pay.received_by_user_id
      WHERE pay.id=%s
      """,
      (payment_id,),
    )
    return cur.fetchone()
  finally:
    cur.close()
    conn.close()

def get_payment_receipt_student(payment_id: int, student_id: int):
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT
        pay.id,
        pay.paid_amount,
        DATE_FORMAT(pay.paid_at, '%Y-%m-%d %H:%i') AS paid_at,
        pay.note,
        p.class_no, p.section, p.academic_year, p.fee_month, p.amount AS plan_amount,
        ru.phone AS received_by_phone
      FROM fee_payments pay
      JOIN fee_plans p ON p.id = pay.fee_plan_id
      JOIN users ru ON ru.id = pay.received_by_user_id
      WHERE pay.id=%s AND pay.student_id=%s
      """,
      (payment_id, student_id),
    )
    return cur.fetchone()
  finally:
    cur.close()
    conn.close()
