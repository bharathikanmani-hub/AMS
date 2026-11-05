"""Create a faculty (or hod/admin) account from the command line.

    python create_staff.py --role faculty --name "Dr. Kumar" --email kumar@college.edu

The password is typed at a hidden prompt (never stored in shell history).
"""

import argparse
import getpass
import sys

from app import create_app
from extensions import db
from models import User


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--role", choices=["faculty", "hod", "admin"], default="faculty")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    args = p.parse_args()

    email = args.email.strip().lower()
    password = getpass.getpass("Password (min 6 chars): ")
    if len(password) < 6 or password != getpass.getpass("Confirm password: "):
        print("Password too short or does not match.")
        return 1

    app = create_app()
    with app.app_context():
        if User.query.filter(db.func.lower(User.email) == email).first():
            print("A user with that e-mail already exists.")
            return 1
        user = User(email=email, name=args.name.strip(), role=args.role, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"{args.role} account created. Sign in with ID: {user.id}  (role: {args.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
