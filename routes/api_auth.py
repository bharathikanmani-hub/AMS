"""JSON authentication API for the AttendAI React frontend.

  GET  /api/auth/csrf     -> {"csrf_token": "..."}   (call once on page load)
  POST /api/auth/signup   -> {name, email, role, roll_number (students), password, confirm_password}
                             students: active at once; faculty/admin: wait for admin approval
  POST /api/auth/login    -> {role, identifier, password}   (identifier = roll number, ID or e-mail)
  POST /api/auth/forgot   -> {email}  e-mails a 6-digit code (always answers the same way)
  POST /api/auth/reset    -> {email, otp, new_password}
  POST /api/auth/logout
  GET  /api/auth/me       -> current session user, or 401

All POSTs need the header  X-CSRFToken: <token from /api/auth/csrf>
and the browser must send cookies (fetch ... credentials: 'include').
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf.csrf import generate_csrf

from services.auth_service import (
    ROLES,
    AuthError,
    account_pending,
    authenticate,
    clear_failures,
    find_user_by_email,
    is_throttled,
    normalize_identifier,
    record_failure,
    signup_account,
    validate_registration,
)
from services.otp_service import request_otp, reset_password

api_auth_bp = Blueprint("api_auth", __name__, url_prefix="/api/auth")


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def user_payload(user) -> dict:
    payload = {"id": user.id, "name": user.name, "role": user.role}
    if user.role == "student" and getattr(user, "student_profile", None):
        payload["roll_number"] = user.student_profile.roll_number
        payload["identifier"] = user.student_profile.roll_number   # shown in the UI header
    else:
        payload["email"] = user.email
        payload["identifier"] = str(user.id)                        # the "Admin ID" / "Faculty ID"
    return payload


def _json_body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@api_auth_bp.get("/csrf")
def csrf_token():
    return _no_store(jsonify({"csrf_token": generate_csrf()}))


@api_auth_bp.post("/signup")
def signup():
    data = _json_body()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "student").strip().lower()
    roll = normalize_identifier(data.get("roll_number") or data.get("rollNumber"))
    password = data.get("password") or ""

    throttle_key = f"{request.remote_addr}|signup"
    if is_throttled(throttle_key):
        return jsonify({"ok": False, "message": "Too many sign-up attempts. Please wait a few minutes."}), 429
    error = validate_registration(name, email, role, roll, password, data.get("confirm_password"))
    if error:
        return jsonify({"ok": False, "message": error}), 400
    try:
        user, pending = signup_account(name, email, role, roll, password)
    except AuthError as exc:
        record_failure(throttle_key)
        return jsonify({"ok": False, "message": exc.message}), exc.status

    message = (
        "Request sent. An administrator must approve your account before you can sign in."
        if pending else "Account created. You can now sign in."
    )
    return jsonify({"ok": True, "pending": pending, "message": message, "user": user_payload(user)}), 201


@api_auth_bp.post("/login")
def login():
    data = _json_body()
    role = (data.get("role") or "student").strip().lower()
    identifier = normalize_identifier(data.get("identifier") or data.get("roll_number"))
    password = data.get("password") or ""

    if role not in ROLES:
        return jsonify({"ok": False, "message": "Please choose a valid role."}), 400
    if not identifier or not password:
        return jsonify({"ok": False, "message": "Please enter your ID and password."}), 400

    throttle_key = f"{request.remote_addr}|{role}|{identifier.lower()}"
    if is_throttled(throttle_key):
        return jsonify(
            {"ok": False, "message": "Too many failed attempts. Please wait a few minutes."}
        ), 429

    user = authenticate(identifier, password, role)
    if user is None:
        if account_pending(identifier, password, role):
            return jsonify({"ok": False, "pending": True,
                            "message": "Your account is waiting for administrator approval."}), 403
        record_failure(throttle_key)
        return jsonify({"ok": False, "message": "Invalid ID or password for this role."}), 401

    clear_failures(throttle_key)
    session.clear()  # drop any pre-login session data (prevents fixation)
    session["active_role"] = user.role
    login_user(user, remember=False)
    session.permanent = True
    return _no_store(jsonify({"ok": True, "message": "Signed in.", "user": user_payload(user)}))


def _mail_mode() -> str:
    from services.email_service import is_smtp_configured
    return "email" if is_smtp_configured() else "console"


@api_auth_bp.post("/forgot")
def forgot():
    """Always answers the same way, so nobody can find out which e-mails are registered."""
    email = (_json_body().get("email") or "").strip().lower()
    key = f"{request.remote_addr}|forgot"
    if is_throttled(key):
        return jsonify({"ok": False, "message": "Too many requests. Please wait a few minutes."}), 429
    record_failure(key)                     # counts every request (cheap per-IP rate limit)
    if email:
        user = find_user_by_email(email)
        if user is not None:
            try:
                request_otp(user)
            except Exception:
                current_app.logger.exception("OTP request failed")
    return jsonify({
        "ok": True,
        "delivery": _mail_mode(),           # a SERVER setting, not about this e-mail address
        "message": "If this e-mail is registered, a 6-digit code has been sent. It is valid for 10 minutes.",
    })


@api_auth_bp.post("/reset")
def reset():
    data = _json_body()
    email = (data.get("email") or "").strip().lower()
    code = (data.get("otp") or "").strip()
    new_password = data.get("new_password") or ""
    key = f"{request.remote_addr}|reset|{email}"
    if is_throttled(key):
        return jsonify({"ok": False, "message": "Too many attempts. Please request a new code later."}), 429
    user = find_user_by_email(email) if email else None
    try:
        if user is None or not code.isdigit() or len(code) != 6:
            raise AuthError("Invalid or expired code.", 400)
        reset_password(user, code, new_password)
    except AuthError as exc:
        record_failure(key)
        return jsonify({"ok": False, "message": exc.message}), exc.status
    clear_failures(key)
    return jsonify({"ok": True, "message": "Password changed. You can now sign in."})


@api_auth_bp.post("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    session.clear()
    return jsonify({"ok": True, "message": "Signed out."})


@api_auth_bp.get("/me")
@login_required
def me():
    return _no_store(jsonify({"ok": True, "user": user_payload(current_user)}))
