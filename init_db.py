"""One-time setup: create any missing tables and the first admin account.

Run this YOURSELF after the MySQL database exists:

    python init_db.py

* Uses the DB_* settings from your .env (never printed).
* db.create_all() only creates tables that are missing - it never drops or
  alters existing tables or data.
* The admin is created from ADMIN_NAME / ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_PHONE
  in .env, only if no user with that e-mail exists yet.
"""

import os
import sys

from app import create_app
from extensions import db
from models import User


def main() -> int:
    app = create_app()
    with app.app_context():
        try:
            db.create_all()
        except Exception as exc:  # connection refused, unknown database, bad credentials...
            print("\nCould not connect to / set up MySQL:")
            print(f"  {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
            print("\nCheck that MySQL is running and the database in DB_NAME exists:")
            print("  CREATE DATABASE classroom_attendance CHARACTER SET utf8mb4;")
            return 1
        print("Tables are ready.")

        email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD") or ""
        if not email or not password:
            print("ADMIN_EMAIL / ADMIN_PASSWORD not set in .env - skipping admin creation.")
            return 0
        if User.query.filter(db.func.lower(User.email) == email).first():
            existing = User.query.filter(db.func.lower(User.email) == email).first()
            print(f"Admin account already exists - sign in with ID: {existing.id}")
            return 0

        admin = User(
            email=email,
            name=(os.getenv("ADMIN_NAME") or "Administrator").strip(),
            phone=(os.getenv("ADMIN_PHONE") or None),
            role="admin",
            is_active=True,
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin account created. Sign in as Admin with ID: {admin.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
