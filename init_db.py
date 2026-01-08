from db import connect_server, get_db_config



def main():
    cfg = get_db_config()
    db_name = cfg["database"]

    conn = connect_server()
    cursor = conn.cursor()

    cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
    conn.commit()

    cursor.close()
    conn.close()

    print(f"✅ Database ensured: {db_name}")


if __name__ == "__main__":
    main()
