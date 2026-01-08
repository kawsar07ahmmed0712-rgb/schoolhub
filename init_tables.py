import os
from db import connect_db
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

def create_users_table():
    conn = connect_db()
    cursor = conn.cursor()

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

    conn.commit()
    cursor.close()
    conn.close()

def seed_admin_user():
    admin_phone = os.getenv("ADMIN_PHONE", "01700000000")
    admin_password = os.getenv("ADMIN_PASSWORD", "1234")

    password_hash = generate_password_hash(admin_password)

    conn = connect_db()
    cursor = conn.cursor()

    # Check if admin already exists
    cursor.execute("SELECT id FROM users WHERE phone = %s", (admin_phone,))
    row = cursor.fetchone()

    if row is None:
        cursor.execute(
            "INSERT INTO users (phone, password_hash, role) VALUES (%s, %s, %s)",
            (admin_phone, password_hash, "admin"),
        )
        conn.commit()
        print(f"✅ Admin user created: {admin_phone}")
    else:
        print(f"ℹ️ Admin user already exists: {admin_phone}")

    cursor.close()
    conn.close()

def main():
    create_users_table()
    seed_admin_user()
    print("✅ Tables ensured + seed done")

if __name__ == "__main__":
    main()