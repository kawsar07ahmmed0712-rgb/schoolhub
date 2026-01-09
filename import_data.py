import os
import csv
import glob
from datetime import datetime

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from db import connect_db

load_dotenv()

STUDENTS_DATA_DIR = os.getenv("STUDENTS_DATA_DIR", "Database/Data")
TEACHERS_CSV = os.getenv("TEACHERS_CSV", "Database/schoolhub_teachers_20_class_teachers.csv")
ADMIN_CSV = os.getenv("ADMIN_CSV", "Database/schoolhub_admin.csv")
HEADMASTER_CSV = os.getenv("HEADMASTER_CSV", "Database/schoolhub_headmaster.csv")

ACADEMIC_YEAR = int(os.getenv("ACADEMIC_YEAR", str(datetime.now().year)))



def get_or_create_user(cursor, phone: str, plain_password: str, role: str) -> int:
    cursor.execute("SELECT id, role FROM users WHERE phone=%s", (phone,))
    row = cursor.fetchone()
    if row:
        return row[0]

    password_hash = generate_password_hash(plain_password)
    cursor.execute(
        "INSERT INTO users (phone, password_hash, role) VALUES (%s, %s, %s)",
        (phone, password_hash, role),
    )
    return cursor.lastrowid


def get_or_create_student(cursor, user_id: int, name: str) -> int:
    cursor.execute("SELECT id FROM students WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        "INSERT INTO students (user_id, name) VALUES (%s, %s)",
        (user_id, name),
    )
    return cursor.lastrowid


def ensure_student_enrollment(cursor, student_id: int, class_no: int, section: str, roll: int):
    # If same class/section/roll/year exists, ignore
    cursor.execute(
        """
        INSERT IGNORE INTO student_enrollments
        (student_id, class_no, section, roll, academic_year, is_current)
        VALUES (%s, %s, %s, %s, %s, 1)
        """,
        (student_id, class_no, section, roll, ACADEMIC_YEAR),
    )


def get_or_create_teacher(cursor, user_id: int, teacher_code: str, name: str) -> int:
    cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (user_id,))
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


def get_or_create_admin(cursor, user_id: int, secret_id: str, name: str):
    cursor.execute("SELECT id FROM admins WHERE user_id=%s", (user_id,))
    if cursor.fetchone():
        return
    cursor.execute(
        "INSERT INTO admins (user_id, secret_id, name) VALUES (%s, %s, %s)",
        (user_id, secret_id, name),
    )


def get_or_create_headmaster(cursor, user_id: int, authentication_id: str, name: str):
    cursor.execute("SELECT id FROM headmasters WHERE user_id=%s", (user_id,))
    if cursor.fetchone():
        return
    cursor.execute(
        "INSERT INTO headmasters (user_id, authentication_id, name) VALUES (%s, %s, %s)",
        (user_id, authentication_id, name),
    )


def parse_class_teacher_for(text: str):
    # Example: "Class 1-A" or "Class 10-B"
    # We'll extract class_no and section from the last part "1-A" / "10-B"
    parts = text.strip().split()
    last = parts[-1]  # "1-A"
    class_part, section = last.split("-")
    return int(class_part), section.upper()


def import_students(cursor):
    pattern = os.path.join(STUDENTS_DATA_DIR, "class_*_section_*_students_50.csv")


    files = sorted(glob.glob(pattern))

    count = 0
    for path in files:
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                class_no = int(row["class"])
                section = row["section"].strip().upper()
                roll = int(row["roll"])
                name = row["username"].strip()
                phone = row["phone"].strip()
                password = row["password"].strip()

                user_id = get_or_create_user(cursor, phone, password, "student")
                student_id = get_or_create_student(cursor, user_id, name)
                ensure_student_enrollment(cursor, student_id, class_no, section, roll)

                count += 1
    return count, len(files)


def import_teachers(cursor):
    path = TEACHERS_CSV

    if not os.path.exists(path):
        return 0, False

    count = 0
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            teacher_code = row["teacher_id"].strip()
            name = row["teacher_name"].strip()
            phone = row["phone"].strip()
            password = row["password"].strip()
            class_teacher_for = row["class_teacher_for"].strip()

            class_no, section = parse_class_teacher_for(class_teacher_for)

            user_id = get_or_create_user(cursor, phone, password, "teacher")
            teacher_id = get_or_create_teacher(cursor, user_id, teacher_code, name)
            ensure_class_teacher_assignment(cursor, teacher_id, class_no, section)

            count += 1
    return count, True


def import_admin(cursor):
    path = ADMIN_CSV


    if not os.path.exists(path):
        return 0, False

    count = 0
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            secret_id = row["secret_id"].strip()
            name = row["admin_name"].strip()
            phone = row["phone"].strip()
            password = row["secret_password"].strip()

            user_id = get_or_create_user(cursor, phone, password, "admin")
            get_or_create_admin(cursor, user_id, secret_id, name)
            count += 1
    return count, True


def import_headmaster(cursor):
    path = HEADMASTER_CSV

    if not os.path.exists(path):
        return 0, False

    count = 0
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            auth_id = row["authentication_id"].strip()
            name = row["headmaster_name"].strip()
            phone = row["phone"].strip()
            password = row["password"].strip()

            # NOTE: users.role enum currently includes 'head' (not 'headmaster')
            user_id = get_or_create_user(cursor, phone, password, "head")
            get_or_create_headmaster(cursor, user_id, auth_id, name)
            count += 1
    return count, True


def main():
    conn = connect_db()
    cursor = conn.cursor()

    s_count, s_files = import_students(cursor)
    t_count, t_ok = import_teachers(cursor)
    a_count, a_ok = import_admin(cursor)
    h_count, h_ok = import_headmaster(cursor)

    conn.commit()
    cursor.close()
    conn.close()

    print(f"✅ Students imported: {s_count} (from {s_files} files)")
    print(f"✅ Teachers imported: {t_count} (found file: {t_ok})")
    print(f"✅ Admin imported: {a_count} (found file: {a_ok})")
    print(f"✅ Headmaster imported: {h_count} (found file: {h_ok})")
    print("✅ Done")


if __name__ == "__main__":
    main()
