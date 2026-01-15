from db import connect_db

def main():
    conn = connect_db()
    cursor = conn.cursor()

    # 1) Weekly schedule: which teacher teaches which class on which weekday+period
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_schedule_slots (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_id INT NOT NULL,

            weekday ENUM('sun','mon','tue','wed','thu','fri','sat') NOT NULL,
            period_no TINYINT NOT NULL,

            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,

            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

            UNIQUE KEY uq_teacher_weekday_period (teacher_id, weekday, period_no),
            INDEX idx_teacher_weekday (teacher_id, weekday),

            CONSTRAINT fk_tss_teacher
              FOREIGN KEY (teacher_id) REFERENCES teachers(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    # 2) Daily log/tick: teacher marks done + writes topic/homework/notes for a specific date+period
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_lesson_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_id INT NOT NULL,

            log_date DATE NOT NULL,
            period_no TINYINT NOT NULL,

            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,

            topic VARCHAR(255) NOT NULL DEFAULT '',
            homework TEXT,
            notes TEXT,

            is_done TINYINT(1) NOT NULL DEFAULT 0,
            done_at TIMESTAMP NULL,

            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
              ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY uq_teacher_date_period (teacher_id, log_date, period_no),
            INDEX idx_teacher_date (teacher_id, log_date),

            CONSTRAINT fk_tll_teacher
              FOREIGN KEY (teacher_id) REFERENCES teachers(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    conn.commit()
    cursor.close()
    conn.close()

    print("OK. Tables ensured: teacher_schedule_slots, teacher_lesson_logs")

if __name__ == "__main__":
    main()
