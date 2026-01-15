from db import connect_db

def main():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_id INT NOT NULL,
            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,
            attendance_date DATE NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_class_section_date (class_no, section, attendance_date),
            INDEX idx_teacher (teacher_id),
            CONSTRAINT fk_att_teacher
              FOREIGN KEY (teacher_id) REFERENCES teachers(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id INT NOT NULL,
            student_id INT NOT NULL,
            status ENUM('present','absent') NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_session_student (session_id, student_id),
            INDEX idx_session (session_id),
            CONSTRAINT fk_att_rec_session
              FOREIGN KEY (session_id) REFERENCES attendance_sessions(id)
              ON DELETE CASCADE,
            CONSTRAINT fk_att_rec_student
              FOREIGN KEY (student_id) REFERENCES students(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    conn.commit()
    cursor.close()
    conn.close()
    print("OK. Attendance tables ensured")

if __name__ == "__main__":
    main()
