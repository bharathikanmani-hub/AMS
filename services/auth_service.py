"""Authentication helpers shared by the JSON API and the HTML login pages.

Sign-in rules (matches the AttendAI React UI):
  * student        -> Roll Number (or e-mail) + password
  * faculty/admin  -> numeric account ID (users.id) or the account e-mail, + password
Sign-up collects name, e-mail, role and password (students also give a roll number):
  * student        -> account is active immediately
  * faculty/admin  -> account is created INACTIVE and waits for an administrator's approval
                      (otherwise anyone could make themselves an admin)
"""

from __future__ import annotations

import re
import threading
import time
from typing import Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import AuditLog, SignupRequest, Student, User

ROLES = ("admin", "faculty", "student")
ROLL_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
MIN_PASSWORD_LEN = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SIGNUP_ROLES = ("student", "faculty", "admin")
MAX_PASSWORD_LEN = 128
PLACEHOLDER_EMAIL_DOMAIN = "attendai.local"

# Compared against when the account doesn't exist, so response time
# doesn't reveal whether a roll number / ID is registered.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class AuthError(Exception):
    """Raised for expected, user-facing auth failures."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# Brute-force throttle (in-memory, per process): 8 failures / 5 minutes.
# --------------------------------------------------------------------------
_WINDOW_SECONDS = 300
_MAX_FAILURES = 8
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


def _recent(key: str) -> list[float]:
    cutoff = time.time() - _WINDOW_SECONDS
    hits = [t for t in _failures.get(key, []) if t > cutoff]
    if hits:
        _failures[key] = hits
    else:
        _failures.pop(key, None)
    return hits


def is_throttled(key: str) -> bool:
    with _lock:
        return len(_recent(key)) >= _MAX_FAILURES


def record_failure(key: str) -> None:
    with _lock:
        _recent(key)
        _failures.setdefault(key, []).append(time.time())
        if len(_failures) > 5000:  # keep memory bounded
            for k in list(_failures)[:1000]:
                _recent(k)


def clear_failures(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def normalize_identifier(value: Optional[str]) -> str:
    return (value or "").strip()


def validate_signup(roll: str, password: str, confirm: Optional[str]) -> Optional[str]:
    """Return an error message, or None if the input is acceptable."""
    if not roll:
        return "Roll number is required."
    if not ROLL_RE.match(roll):
        return "Roll number must be 3-30 characters: letters, digits, '.', '_' or '-'."
    if not password:
        return "Password is required."
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password) > MAX_PASSWORD_LEN:
        return f"Password must be at most {MAX_PASSWORD_LEN} characters."
    if confirm is not None and password != confirm:
        return "Passwords do not match."
    return None


def validate_registration(name: str, email: str, role: str, roll: str, password: str, confirm: Optional[str]) -> Optional[str]:
    """Return an error message for the sign-up form, or None if it is acceptable."""
    if not 2 <= len((name or "").strip()) <= 100:
        return "Enter your full name (2-100 characters)."
    if not EMAIL_RE.match(email or "") or len(email) > 120:
        return "Enter a valid e-mail address."
    if role not in SIGNUP_ROLES:
        return "Choose Student, Faculty or Admin."
    if role == "student":
        if not roll:
            return "Roll number is required for students."
        if not ROLL_RE.match(roll):
            return "Roll number must be 3-30 characters: letters, digits, '.', '_' or '-'."
    if not password:
        return "Password is required."
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password) > MAX_PASSWORD_LEN:
        return f"Password must be at most {MAX_PASSWORD_LEN} characters."
    if confirm is not None and password != confirm:
        return "Passwords do not match."
    return None


# --------------------------------------------------------------------------
# Lookups / authentication
# --------------------------------------------------------------------------
def find_student_by_roll(roll: str) -> Optional[Student]:
    if not roll:
        return None
    return Student.query.filter(func.upper(Student.roll_number) == roll.upper()).first()


def find_user_by_email(email: str, role: Optional[str] = None) -> Optional[User]:
    if not email:
        return None
    q = User.query.filter(func.lower(User.email) == email.lower())
    if role:
        q = q.filter(User.role == role)
    return q.first()


def _lookup(identifier: str, role: str) -> Optional[User]:
    identifier = normalize_identifier(identifier)
    if "@" in identifier:                                   # e-mail works for every role
        return find_user_by_email(identifier, role)
    if role == "student":
        student = find_student_by_roll(identifier)
        return student.user if student else None
    if identifier.isdigit() and len(identifier) <= 9:       # "Admin ID" / "Faculty ID" = users.id
        candidate = db.session.get(User, int(identifier))
        return candidate if candidate is not None and candidate.role == role else None
    return None


def authenticate(identifier: str, password: str, role: str) -> Optional[User]:
    """Return the User on success, otherwise None (never says which part failed)."""
    role = (role or "student").strip().lower()
    if role not in ROLES or not normalize_identifier(identifier) or not password:
        return None
    user = _lookup(identifier, role)
    if user is None or not user.password_hash:
        check_password_hash(_DUMMY_HASH, password)  # equalise timing
        return None
    if not user.is_active:
        return None
    return user if user.check_password(password) else None


def account_pending(identifier: str, password: str, role: str) -> bool:
    """True only if the credentials are CORRECT but the account still awaits admin approval."""
    role = (role or "").strip().lower()
    if role not in ROLES or not password:
        return False
    user = _lookup(identifier, role)
    if user is None or user.is_active or not user.password_hash or not user.check_password(password):
        return False
    return SignupRequest.query.filter_by(user_id=user.id).first() is not None


# --------------------------------------------------------------------------
# Student self sign-up
# --------------------------------------------------------------------------
def signup_account(name: str, email: str, role: str, roll: str, password: str) -> Tuple[User, bool]:
    """Create an account. Returns (user, pending_approval). Raises AuthError."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    role = (role or "").strip().lower()
    roll = normalize_identifier(roll)
    error = validate_registration(name, email, role, roll, password, None)
    if error:
        raise AuthError(error, 400)

    if find_user_by_email(email):
        raise AuthError("An account with this e-mail already exists. Please sign in.", 409)
    if role == "student" and find_student_by_roll(roll):
        raise AuthError("An account with this roll number already exists. Please sign in.", 409)

    pending = role in ("faculty", "admin")
    try:
        user = User(email=email, name=name, role=role, is_active=not pending)
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        if role == "student":
            db.session.add(Student(user_id=user.id, roll_number=roll, year=1))
        else:
            db.session.add(SignupRequest(user_id=user.id, requested_role=role))
        db.session.add(
            AuditLog(
                user_id=user.id,
                action="signup_request" if pending else "student_signup",
                entity_type="User",
                entity_id=user.id,
                new_value=f"role={role}",
            )
        )
        db.session.commit()
        return user, pending
    except IntegrityError:
        db.session.rollback()
        raise AuthError("An account with this e-mail or roll number already exists.", 409)
    except Exception:
        db.session.rollback()
        raise
