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
    cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS notices (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(200) NOT NULL,
        body TEXT NOT NULL,
        by_user_id INT NOT NULL,
        by_role ENUM('teacher','head','admin') NOT NULL,
        by_phone VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL,
        INDEX idx_created_at (created_at),
        CONSTRAINT fk_notices_user FOREIGN KEY (by_user_id) REFERENCES users(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS school_settings (
            `key` VARCHAR(64) NOT NULL PRIMARY KEY,
            `value` TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
              ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
      """
      CREATE TABLE IF NOT EXISTS fee_plans (
        id INT AUTO_INCREMENT PRIMARY KEY,
        class_no TINYINT NOT NULL,
        section ENUM('A','B') NOT NULL,
        academic_year INT NOT NULL,
        fee_month TINYINT NOT NULL,
        amount INT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_plan (class_no, section, academic_year, fee_month)
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
      """
    )


    cursor.execute(
      """
      CREATE TABLE IF NOT EXISTS fee_payments (
        id INT AUTO_INCREMENT PRIMARY KEY,
        fee_plan_id INT NOT NULL,
        student_id INT NOT NULL,
        paid_amount INT NOT NULL,
        paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        received_by_user_id INT NOT NULL,
        note VARCHAR(255) NULL,
        INDEX idx_student (student_id),
        INDEX idx_plan (fee_plan_id),
        CONSTRAINT fk_payment_plan FOREIGN KEY (fee_plan_id) REFERENCES fee_plans(id) ON DELETE CASCADE,
        CONSTRAINT fk_payment_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
        CONSTRAINT fk_payment_receiver FOREIGN KEY (received_by_user_id) REFERENCES users(id) ON DELETE CASCADE
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
      """
    )

    cursor.execute(
      """
      CREATE TABLE IF NOT EXISTS fee_payment_requests (
        id INT AUTO_INCREMENT PRIMARY KEY,
        student_id INT NOT NULL,
        class_no TINYINT NOT NULL,
        section ENUM('A','B') NOT NULL,
        academic_year INT NOT NULL,
        fee_month TINYINT NOT NULL,
        requested_amount INT NOT NULL,
        note VARCHAR(255) NULL,
        status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
        requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        decided_by_user_id INT NULL,
        decided_at TIMESTAMP NULL,
        INDEX idx_student (student_id),
        INDEX idx_status (status),
        INDEX idx_plan (class_no, section, academic_year, fee_month),
        CONSTRAINT fk_fee_req_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
        CONSTRAINT fk_fee_req_decider FOREIGN KEY (decided_by_user_id) REFERENCES users(id) ON DELETE SET NULL
      ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
      """
    )

    # Results / marks
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS exams (
            id INT AUTO_INCREMENT PRIMARY KEY,
            academic_year INT NOT NULL,
            name VARCHAR(60) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_exam (academic_year, name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS exam_publications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            exam_id INT NOT NULL,
            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,
            is_published TINYINT(1) NOT NULL DEFAULT 0,
            published_by_user_id INT NOT NULL,
            published_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_pub (exam_id, class_no, section),
            CONSTRAINT fk_pub_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
            CONSTRAINT fk_pub_user FOREIGN KEY (published_by_user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS marks (
            id INT AUTO_INCREMENT PRIMARY KEY,
            exam_id INT NOT NULL,
            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,
            student_id INT NOT NULL,
            subject VARCHAR(60) NOT NULL,
            marks_obtained DECIMAL(5,2) NOT NULL,
            max_marks DECIMAL(5,2) NOT NULL DEFAULT 100,
            entered_by_user_id INT NOT NULL,
            entered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_mark (exam_id, class_no, section, student_id, subject),
            INDEX idx_student (student_id),
            INDEX idx_exam (exam_id),
            CONSTRAINT fk_mark_exam FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
            CONSTRAINT fk_mark_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            CONSTRAINT fk_mark_user FOREIGN KEY (entered_by_user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    # Leave requests
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            student_id INT NOT NULL,
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            reason VARCHAR(500) NOT NULL,
            status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
            decided_by_user_id INT NULL,
            decided_at TIMESTAMP NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_student (student_id),
            INDEX idx_status (status),
            CONSTRAINT fk_leave_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            CONSTRAINT fk_leave_decider FOREIGN KEY (decided_by_user_id) REFERENCES users(id) ON DELETE SET NULL
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
    print("OK. Tables ensured: users + role tables + 20 class tables")


if __name__ == "__main__":
    main()
