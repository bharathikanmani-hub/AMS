"""E-mail OTP for password reset.

* 6-digit random code (secrets), valid for 10 minutes, usable once.
* Only a salted hash is stored in the database (table otp_tokens) - never the code itself.
* At most 5 wrong guesses per code; at most 3 codes per account per 15 minutes; 60 s between codes.
* The code is e-mailed with the existing send_email() (MAIL_EMAIL / MAIL_APP_PASSWORD in .env).
* If SMTP is NOT configured, the code is printed in the server window instead (development only),
  unless MAIL_DEV_PRINT_OTP=false.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

from flask import current_app

from extensions import db
from models import AuditLog, OtpToken, User
from services.auth_service import AuthError, MAX_PASSWORD_LEN, MIN_PASSWORD_LEN, PLACEHOLDER_EMAIL_DOMAIN

log = logging.getLogger(__name__)

OTP_MINUTES = 10
MAX_ATTEMPTS = 5
MAX_CODES_PER_15_MIN = 3
COOLDOWN_SECONDS = 60


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _hash(salt: str, code: str) -> str:
    key = (current_app.config.get("SECRET_KEY") or "").encode()
    return hmac.new(key, f"{salt}:{code}".encode(), hashlib.sha256).hexdigest()


def can_email(user: User) -> bool:
    return bool(user.email) and not user.email.lower().endswith("@" + PLACEHOLDER_EMAIL_DOMAIN)


def request_otp(user: User) -> Tuple[bool, str]:
    """Create + deliver a code. Returns (ok, mode) where mode is 'email', 'console' or a reason.
    The caller must NOT reveal this to the requester (it would leak which e-mails are registered)."""
    now = datetime.now(timezone.utc)
    if not user.is_active or not can_email(user):
        return False, "ineligible"
    recent = (OtpToken.query.filter(OtpToken.user_id == user.id,
                                    OtpToken.created_at >= now - timedelta(minutes=15))
              .order_by(OtpToken.created_at.desc()).all())
    if len(recent) >= MAX_CODES_PER_15_MIN:
        return False, "rate_limited"
    if recent and (now - _aware(recent[0].created_at)).total_seconds() < COOLDOWN_SECONDS:
        return False, "cooldown"

    OtpToken.query.filter_by(user_id=user.id, used=False).update({"used": True})   # one live code at a time
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    db.session.add(OtpToken(user_id=user.id, salt=salt, code_hash=_hash(salt, code),
                            expires_at=now + timedelta(minutes=OTP_MINUTES)))
    db.session.add(AuditLog(user_id=user.id, action="otp_requested", entity_type="User", entity_id=user.id))
    db.session.commit()

    subject = "AttendAI password reset code"
    body = (f"Hello {user.name},\n\nYour AttendAI password reset code is:\n\n    {code}\n\n"
            f"It is valid for {OTP_MINUTES} minutes and can be used once.\n"
            "If you did not ask for this, ignore this e-mail - your password has not changed.\n\nAttendAI")
    from services.email_service import is_smtp_configured, send_email
    if is_smtp_configured():
        ok, msg = send_email(user.email, subject, body)
        if not ok:
            log.error("OTP e-mail failed for user %s: %s", user.id, msg)
            print(f"\n[AttendAI] E-mail could not be sent ({msg}).", flush=True)
            if current_app.config.get("MAIL_DEV_PRINT_OTP", True):     # never leave the user locked out while testing
                print(f"[AttendAI DEV] Password reset code for {user.email}: {code}  (valid {OTP_MINUTES} min)\n", flush=True)
            return False, "email_failed"
        return True, "email"
    if current_app.config.get("MAIL_DEV_PRINT_OTP", True):
        log.warning("=== DEV MODE (SMTP not configured) === password reset code for %s: %s", user.email, code)
        print(f"\n[AttendAI DEV] Password reset code for {user.email}: {code}  (valid {OTP_MINUTES} min)\n", flush=True)
        return True, "console"
    return False, "smtp_not_configured"


def reset_password(user: User, code: str, new_password: str) -> None:
    """Verify the code and set the new password. Raises AuthError with a deliberately vague message."""
    generic = AuthError("Invalid or expired code.", 400)
    if not (MIN_PASSWORD_LEN <= len(new_password or "") <= MAX_PASSWORD_LEN):
        raise AuthError(f"Password must be {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} characters.", 400)
    now = datetime.now(timezone.utc)
    token = (OtpToken.query.filter_by(user_id=user.id, used=False)
             .order_by(OtpToken.created_at.desc()).first())
    if token is None or _aware(token.expires_at) < now or token.attempts >= MAX_ATTEMPTS:
        raise generic
    token.attempts += 1
    ok = hmac.compare_digest(token.code_hash, _hash(token.salt, (code or "").strip()))
    if not ok:
        db.session.commit()                    # persist the failed attempt
        raise generic
    token.used = True
    user.set_password(new_password)
    OtpToken.query.filter_by(user_id=user.id, used=False).update({"used": True})
    db.session.add(AuditLog(user_id=user.id, action="password_reset", entity_type="User", entity_id=user.id))
    db.session.commit()
