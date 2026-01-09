from db import connect_db

# Assumption:
# section A -> section_01, section B -> section_02
SECTION_MAP = {"A": "01", "B": "02"}

def make_table_name(class_no: int, section_code: str) -> str:
    return f"class_{class_no:02d}_section_{section_code}"

def main():
    conn = connect_db()
    cursor = conn.cursor()

    for class_no in range(1, 11):  # Class 01 to 10
        for section_letter in ("A", "B"):
            section_code = SECTION_MAP[section_letter]
            table_name = make_table_name(class_no, section_code)

            # Each class table stores roster rows linked to the main students table.
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    student_id INT NOT NULL,
                    roll INT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_roll (roll),
                    INDEX idx_student_id (student_id),
                    CONSTRAINT fk_{table_name}_student
                      FOREIGN KEY (student_id) REFERENCES students(id)
                      ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Class tables ensured: class_01_section_01 ... class_10_section_02")

if __name__ == "__main__":
    main()
