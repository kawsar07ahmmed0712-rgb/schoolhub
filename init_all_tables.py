from db import connect_db

# Your naming requirement:
# Section A -> section_01, Section B -> section_02
SECTION_MAP = {"A": "01", "B": "02"}


def make_class_table_name(class_no: int, section_letter: str) -> str:
    section_code = SECTION_MAP[section_letter]
    return f"class_{class_no:02d}_section_{section_code}"


def main():
    conn = connect_db()
    cursor = conn.cursor()

    # 1) users table (login source of truth)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            phone VARCHAR(20) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role ENUM('student','teacher','head','admin') NOT NULL,
            is_active TINYINT(1) NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    # 2) students profile table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_students_user
              FOREIGN KEY (user_id) REFERENCES users(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    # 3) teachers profile table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS teachers (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL UNIQUE,
            teacher_code VARCHAR(30) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_teachers_user
              FOREIGN KEY (user_id) REFERENCES users(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS class_teacher_assignments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_id INT NOT NULL,
            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,
            academic_year INT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

            UNIQUE KEY uq_class_per_year (class_no, section, academic_year),
            UNIQUE KEY uq_teacher_per_year (teacher_id, academic_year),

            CONSTRAINT fk_cta_teacher
            FOREIGN KEY (teacher_id) REFERENCES teachers(id)
            ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )


    # 4) admins profile table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL UNIQUE,
            secret_id VARCHAR(30) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_admins_user
              FOREIGN KEY (user_id) REFERENCES users(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    # 5) headmasters profile table (login role will be 'head')
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS headmasters (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL UNIQUE,
            authentication_id VARCHAR(30) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_headmasters_user
              FOREIGN KEY (user_id) REFERENCES users(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    # 6) Class tables (class_01_section_01 ... class_10_section_02)
    for class_no in range(1, 11):
        for section_letter in ("A", "B"):
            table_name = make_class_table_name(class_no, section_letter)

            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    student_id INT NOT NULL,
                    roll INT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    UNIQUE KEY uq_roll (roll),
                    UNIQUE KEY uq_student (student_id),
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
    print("✅ Tables ensured: users + role tables + 20 class tables")


if __name__ == "__main__":
    main()
