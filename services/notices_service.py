from typing import List, Dict, Optional
from db import connect_db

MAX_TITLE_LEN = 200
MAX_BODY_LEN = 5000

def _clean_text(s: str, max_len: int) -> str:
  s = (s or "").strip()
  if len(s) > max_len:
    s = s[:max_len]
  return s

def list_notices(limit: int = 200) -> List[Dict]:
  conn = connect_db()
  cur = conn.cursor(dictionary=True)
  try:
    cur.execute(
      """
      SELECT id, title, body, by_role, by_phone, created_at
      FROM notices
      ORDER BY created_at DESC, id DESC
      LIMIT %s
      """,
      (limit,)
    )
    rows = cur.fetchall() or []
    # Format created_at for templates.
    for r in rows:
      if r.get("created_at") is not None:
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M")
    return rows
  finally:
    cur.close()
    conn.close()

def create_notice(
  title: str,
  body: str,
  by_user_id: int,
  by_role: str,
  by_phone: str
) -> int:
  title = _clean_text(title, MAX_TITLE_LEN)
  body = _clean_text(body, MAX_BODY_LEN)

  if title == "" or body == "":
    raise ValueError("Title and body are required.")

  conn = connect_db()
  cur = conn.cursor()
  try:
    cur.execute(
      """
      INSERT INTO notices (title, body, by_user_id, by_role, by_phone, created_at)
      VALUES (%s, %s, %s, %s, %s, NOW())
      """,
      (title, body, by_user_id, by_role, by_phone)
    )
    conn.commit()
    return cur.lastrowid
  finally:
    cur.close()
    conn.close()

def delete_notice(notice_id: int, requester_role: str, requester_user_id: int) -> bool:
  """
  Permission:
  - teacher: only delete own notices
  - head/admin: delete any
  """
  conn = connect_db()
  cur = conn.cursor()
  try:
    if requester_role == "teacher":
      cur.execute(
        "DELETE FROM notices WHERE id=%s AND by_user_id=%s",
        (notice_id, requester_user_id)
      )
    else:
      cur.execute("DELETE FROM notices WHERE id=%s", (notice_id,))

    conn.commit()
    return cur.rowcount > 0
  finally:
    cur.close()
    conn.close()
