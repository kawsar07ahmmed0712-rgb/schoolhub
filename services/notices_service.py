from db import connect_db

ALLOWED_NOTICE_ROLES = {"teacher", "head", "admin"}

def list_notices(limit: int = 100):
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            """
            SELECT n.id, n.title, n.body, n.by_role,
                   u.phone AS by_phone,
                   DATE_FORMAT(n.created_at, '%Y-%m-%d %H:%i') AS created_at
            FROM notices n
            JOIN users u ON u.id = n.by_user_id
            ORDER BY n.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()

def create_notice(title: str, body: str, by_user_id: int, by_role: str):
    if by_role not in ALLOWED_NOTICE_ROLES:
        raise ValueError("Role not allowed to post notices.")
    conn = connect_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO notices (title, body, by_role, by_user_id) VALUES (%s,%s,%s,%s)",
            (title, body, by_role, by_user_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        cur.close()
        conn.close()



def delete_notice(notice_id: int, requester_user_id: int, requester_role: str):
    conn = connect_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT by_user_id FROM notices WHERE id=%s", (notice_id,))
        row = cur.fetchone()
        if not row:
            return False
        owner_id = int(row["by_user_id"])
        if requester_role == "teacher" and owner_id != requester_user_id:
            return False
        cur.execute("DELETE FROM notices WHERE id=%s", (notice_id,))
        conn.commit()
        return True
    finally:
        cur.close()
        conn.close()

