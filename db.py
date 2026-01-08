import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_db_config():
    # Read DB config from .env
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "SchoolHub"),
    }

def connect_server():
    cfg = get_db_config()
    return mysql.connector.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
    )

def connect_db():
    # Connect selecting the database
    cfg = get_db_config()
    return mysql.connector.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
    )