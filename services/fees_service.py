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
