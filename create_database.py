"""Create the MySQL database named in your .env (no MySQL Workbench needed).

    python create_database.py

Uses DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME from .env (never printed).
It only runs CREATE DATABASE IF NOT EXISTS - it never touches existing databases or tables.
"""

import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    name = os.getenv("DB_NAME", "classroom_attendance")

    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
        print("DB_NAME may only contain letters, digits and underscores.")
        return 1

    try:
        import pymysql
        conn = pymysql.connect(host=host, port=port, user=user, password=password, connect_timeout=8)
    except ImportError:
        print("pymysql is not installed. Run:  pip install -r requirements.txt")
        return 1
    except Exception as exc:
        print("Could not connect to MySQL.")
        print(f"  {type(exc).__name__}: {str(exc)[:160]}")
        print("\nCheck that:")
        print("  1. MySQL is installed and RUNNING (Windows: press Win+R, type services.msc, find 'MySQL', click Start)")
        print("  2. DB_HOST, DB_PORT, DB_USER and DB_PASSWORD in your .env are correct")
        return 1

    with conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4")
        conn.commit()
    print(f"Database '{name}' is ready. Next: python init_db.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
