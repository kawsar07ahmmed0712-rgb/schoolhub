import os
import csv

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from db import connect_db

load_dotenv()
ACADEMIC_YEAR = int(os.getenv("ACADEMIC_YEAR", "2026"))


DATABASE_ROOT = os.getenv("DATABASE_ROOT", "Database")

TEACHERS_CSV = os.path.join(DATABASE_ROOT, "schoolhub_teachers_20_class_teachers.csv")
ADMIN_CSV = os.path.join(DATABASE_ROOT, "schoolhub_admin.csv")
HEADMASTER_CSV = os.path.join(DATABASE_ROOT, "schoolhub_headmaster.csv")


def get_or_create_user(cursor, phone: str, plain_password: str, role: str) -> int:
    # 1) Check existing
    cursor.execute("SELECT id FROM users WHERE phone=%s", (phone,))
    row = cursor.fetchone()
    if row:
        return row[0]

    # 2) Create new
    password_hash = generate_password_hash(plain_password)
    cursor.execute(
        "INSERT INTO users (phone, password_hash, role) VALUES (%s, %s, %s)",
        (phone, password_hash, role),
    )
    return cursor.lastrowid

def parse_class_teacher_for(text: str):
    # Expected format like: "Class 1-A" or "Class 10-B"
    parts = text.strip().split()
    last = parts[-1]  # "1-A"
    class_part, section = last.split("-")
    return int(class_part), section.upper()


def ensure_teacher(cursor, user_id: int, teacher_code: str, name: str) -> int:
    cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("SELECT id FROM teachers WHERE teacher_code=%s", (teacher_code,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        "INSERT INTO teachers (user_id, teacher_code, name) VALUES (%s, %s, %s)",
        (user_id, teacher_code, name),
    )
    return cursor.lastrowid

def ensure_class_teacher_assignment(cursor, teacher_id: int, class_no: int, section: str):
    cursor.execute(
        """
        INSERT IGNORE INTO class_teacher_assignments
        (teacher_id, class_no, section, academic_year)
        VALUES (%s, %s, %s, %s)
        """,
        (teacher_id, class_no, section, ACADEMIC_YEAR),
    )



def ensure_admin(cursor, user_id: int, secret_id: str, name: str):
    cursor.execute("SELECT id FROM admins WHERE user_id=%s", (user_id,))
    if cursor.fetchone():
        return

    cursor.execute("SELECT id FROM admins WHERE secret_id=%s", (secret_id,))
    if cursor.fetchone():
        return

    cursor.execute(
        "INSERT INTO admins (user_id, secret_id, name) VALUES (%s, %s, %s)",
        (user_id, secret_id, name),
    )


def ensure_headmaster(cursor, user_id: int, authentication_id: str, name: str):
    cursor.execute("SELECT id FROM headmasters WHERE user_id=%s", (user_id,))
    if cursor.fetchone():
        return

    cursor.execute("SELECT id FROM headmasters WHERE authentication_id=%s", (authentication_id,))
    if cursor.fetchone():
        return

    cursor.execute(
        "INSERT INTO headmasters (user_id, authentication_id, name) VALUES (%s, %s, %s)",
        (user_id, authentication_id, name),
    )


def import_teachers(cursor) -> int:
    if not os.path.exists(TEACHERS_CSV):
        print(f"❌ Teachers CSV not found: {TEACHERS_CSV}")
        return 0

    count = 0
    with open(TEACHERS_CSV, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            teacher_code = row["teacher_id"].strip()
            name = row["teacher_name"].strip()
            phone = row["phone"].strip()
            password = row["password"].strip()
            class_teacher_for = row["class_teacher_for"].strip()

            class_no, section = parse_class_teacher_for(class_teacher_for)

            user_id = get_or_create_user(cursor, phone, password, "teacher")
            teacher_id = ensure_teacher(cursor, user_id, teacher_code, name)
            ensure_class_teacher_assignment(cursor, teacher_id, class_no, section)

            count += 1

    return count


def import_admin(cursor) -> int:
    if not os.path.exists(ADMIN_CSV):
        print(f"❌ Admin CSV not found: {ADMIN_CSV}")
        return 0

    count = 0
    with open(ADMIN_CSV, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            secret_id = row["secret_id"].strip()
            name = row["admin_name"].strip()
            phone = row["phone"].strip()
            password = row["secret_password"].strip()

            user_id = get_or_create_user(cursor, phone, password, "admin")
            ensure_admin(cursor, user_id, secret_id, name)
            count += 1

    return count


def import_headmaster(cursor) -> int:
    if not os.path.exists(HEADMASTER_CSV):
        print(f"❌ Headmaster CSV not found: {HEADMASTER_CSV}")
        return 0

    count = 0
    with open(HEADMASTER_CSV, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            auth_id = row["authentication_id"].strip()
            name = row["headmaster_name"].strip()
            phone = row["phone"].strip()
            password = row["password"].strip()

            # users.role enum uses 'head'
            user_id = get_or_create_user(cursor, phone, password, "head")
            ensure_headmaster(cursor, user_id, auth_id, name)
            count += 1

    return count


def main():
    conn = connect_db()
    cursor = conn.cursor()

    t = import_teachers(cursor)
    a = import_admin(cursor)
    h = import_headmaster(cursor)

    conn.commit()
    cursor.close()
    conn.close()

    print(f"✅ Imported teachers rows processed: {t}")
    print(f"✅ Imported admin rows processed: {a}")
    print(f"✅ Imported headmaster rows processed: {h}")
    print("✅ Done")


if __name__ == "__main__":
    main()
