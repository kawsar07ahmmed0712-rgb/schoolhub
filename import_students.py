import os
import csv
import glob

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from db import connect_db

load_dotenv()

STUDENTS_DATA_DIR = os.getenv("STUDENTS_DATA_DIR", "Database/Data")

SECTION_MAP = {"A": "01", "B": "02"}  # A->section_01, B->section_02 (your DB naming)


def class_table_name(class_no: int, section_letter: str) -> str:
    section_code = SECTION_MAP[section_letter]
    return f"class_{class_no:02d}_section_{section_code}"


def get_or_create_user(cursor, phone: str, plain_password: str) -> int:
    cursor.execute("SELECT id FROM users WHERE phone=%s", (phone,))
    row = cursor.fetchone()
    if row:
        return row[0]

    password_hash = generate_password_hash(plain_password)
    cursor.execute(
        "INSERT INTO users (phone, password_hash, role) VALUES (%s, %s, %s)",
        (phone, password_hash, "student"),
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


def insert_into_class_table(cursor, table_name: str, student_id: int, roll: int):
    # INSERT IGNORE prevents crashing on duplicates (UNIQUE constraint rows are skipped).
    cursor.execute(
        f"INSERT IGNORE INTO `{table_name}` (student_id, roll) VALUES (%s, %s)",
        (student_id, roll),
    )


def import_all_students():
    pattern = os.path.join(STUDENTS_DATA_DIR, "class_*_section_*_students_50.csv")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"ERROR: No student CSV found in: {STUDENTS_DATA_DIR}")
        return

    conn = connect_db()
    cursor = conn.cursor()

    total_rows = 0
    for path in files:
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                class_no = int(row["class"])
                section = row["section"].strip().upper()  # A/B
                roll = int(row["roll"])
                name = row["username"].strip()
                phone = row["phone"].strip()
                password = row["password"].strip()

                user_id = get_or_create_user(cursor, phone, password)
                student_id = get_or_create_student(cursor, user_id, name)

                table = class_table_name(class_no, section)
                insert_into_class_table(cursor, table, student_id, roll)

                total_rows += 1

    conn.commit()
    cursor.close()
    conn.close()

    print(f"OK. Student rows processed: {total_rows}")
    print(f"OK. Student files found: {len(files)}")


if __name__ == "__main__":
    import_all_students()



