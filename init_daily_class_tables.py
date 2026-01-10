from db import connect_db

def main():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_class_days (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teacher_id INT NOT NULL,
            class_no TINYINT NOT NULL,
            section ENUM('A','B') NOT NULL,
            log_date DATE NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

            UNIQUE KEY uq_teacher_date (teacher_id, log_date),

            INDEX idx_teacher (teacher_id),

            CONSTRAINT fk_dcd_teacher
              FOREIGN KEY (teacher_id) REFERENCES teachers(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_class_periods (
            id INT AUTO_INCREMENT PRIMARY KEY,
            day_id INT NOT NULL,
            period_no TINYINT NOT NULL,
            topic VARCHAR(255) NOT NULL DEFAULT '',
            homework TEXT,
            notes TEXT,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
              ON UPDATE CURRENT_TIMESTAMP,

            UNIQUE KEY uq_day_period (day_id, period_no),

            INDEX idx_day (day_id),

            CONSTRAINT fk_dcp_day
              FOREIGN KEY (day_id) REFERENCES daily_class_days(id)
              ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    conn.commit()
    cursor.close()
    conn.close()

    print("✅ Daily class tables ensured: daily_class_days, daily_class_periods")

if __name__ == "__main__":
    main()
