"""Authentication (HTML pages): login, logout, and OTP password reset.

The React frontend uses the JSON API in routes/api_auth.py instead."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import secrets
import smtplib
from urllib.parse import urljoin, urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from werkzeug.security import check_password_hash, generate_password_hash
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length

from extensions import db
from services.auth_service import (
    authenticate,
    clear_failures,
    find_user_by_email,
    is_throttled,
    record_failure,
)

auth_bp = Blueprint("auth", __name__)
otp_storage: dict[str, dict] = {}


class LoginForm(FlaskForm):
    email = StringField("Email / ID", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember Me")
    submit = SubmitField("Log In")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send OTP")


class VerifyOTPForm(FlaskForm):
    otp = StringField(
        "OTP Code",
        validators=[DataRequired(), Length(min=6, max=6, message="OTP must be exactly 6 digits.")],
    )
    submit = SubmitField("Verify OTP")


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=6, message="Password must be at least 6 characters long.")],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Reset Password")


def is_safe_url(target: str) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def find_account_by_email(email: str):
    """Return (role, User) for an e-mail address, or (None, None)."""
    user = find_user_by_email((email or "").strip())
    return (user.role, user) if user else (None, None)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    form = LoginForm()
    if request.method == "POST":
        is_json = request.is_json
        data = request.get_json(silent=True) or {}
        email = (
            form.email.data
            if form.email.data
            else data.get("email") or request.form.get("email", "")
        ).strip().lower()
        password = (
            form.password.data
            if form.password.data
            else data.get("password") or request.form.get("password", "")
        )
        role = (data.get("role") or request.form.get("role") or "").strip().lower()
        remember = bool(request.form.get("remember") or data.get("remember"))

        if not email or not password:
            if is_json:
                return jsonify({"message": "Email and password are required."}), 400
            flash("Please enter both email and password.", "danger")
            return render_template("auth/login.html", form=form), 400

        throttle_key = f"{request.remote_addr}|html|{email}"
        if is_throttled(throttle_key):
            msg = "Too many failed attempts. Please wait a few minutes."
            if is_json:
                return jsonify({"message": msg}), 429
            flash(msg, "danger")
            return render_template("auth/login.html", form=form), 429

        if role:
            user = authenticate(email, password, role)
        else:  # HTML page without a role picker: match the e-mail on any role
            candidate = find_user_by_email(email)
            user = authenticate(email, password, candidate.role) if candidate else None
        if not user:
            record_failure(throttle_key)
            if is_json:
                return jsonify({"message": "Invalid email, password, or role."}), 401
            flash("Invalid email, password, or role.", "danger")
            return render_template("auth/login.html", form=form), 401

        clear_failures(throttle_key)
        session.clear()
        session["active_role"] = user.role
        login_user(user, remember=remember)

        if is_json:
            return jsonify(
                {
                    "message": "Login successful.",
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "name": user.name,
                        "role": user.role,
                    },
                    "redirect": url_for("home"),
                }
            )

        flash(f"Welcome back, {user.name}!", "success")
        next_page = request.args.get("next")
        if next_page and is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for("home"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("auth.login"))


def send_otp_email(receiver_email: str, otp: str) -> tuple[bool, str]:
    sender_user = current_app.config.get("MAIL_EMAIL")
    sender_pwd = current_app.config.get("MAIL_APP_PASSWORD")
    if not sender_user or not sender_pwd:
        current_app.logger.warning("SMTP is not configured; OTP was not sent.")
        return False, "SMTP email service is not configured. Please contact the administrator."

    message = EmailMessage()
    message["Subject"] = "AttendAI Password Reset OTP"
    message["From"] = sender_user
    message["To"] = receiver_email
    message.set_content(
        f"Your one-time password (OTP) is: {otp}\nThis code expires in 10 minutes."
    )
    try:
        with smtplib.SMTP(
            current_app.config.get("MAIL_SMTP_HOST"),
            int(current_app.config.get("MAIL_SMTP_PORT") or 587),
            timeout=10,
        ) as server:
            server.starttls()
            server.login(sender_user, sender_pwd)
            server.send_message(message)
        return True, "OTP sent successfully."
    except Exception as error:
        current_app.logger.exception("SMTP error: %s", error)
        return False, "Failed to send email."


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if request.method != "POST":
        return render_template("auth/forgot_password.html", form=form)

    is_json = request.is_json
    data = request.get_json(silent=True) or {}
    email = (form.email.data or data.get("email") or request.form.get("email", "")).strip().lower()
    if not email:
        if is_json:
            return jsonify({"message": "Please provide your email address."}), 400
        flash("Please enter your registered email address.", "danger")
        return render_template("auth/forgot_password.html", form=form), 400

    account_type, record = find_account_by_email(email)
    if not record:
        if is_json:
            return jsonify({"message": "No account found with this email address."}), 404
        flash("No account found with that email address.", "danger")
        return render_template("auth/forgot_password.html", form=form), 404

    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    otp_hash = generate_password_hash(otp_code)
    session["reset_email"] = email
    session["reset_account_type"] = account_type
    session["reset_otp_hash"] = otp_hash
    session["reset_otp_expires"] = expires_at.isoformat()
    session["otp_verified"] = False
    otp_storage[email] = {"otp_hash": otp_hash, "expires_at": expires_at, "verified": False}

    sent, msg = send_otp_email(email, otp_code)
    if not sent:
        if is_json:
            return jsonify({"message": msg}), 500
        flash(msg, "danger")
        return render_template("auth/forgot_password.html", form=form), 500

    flash("A 6-digit OTP has been sent to your email address.", "info")
    return redirect(url_for("auth.verify_otp"))


@auth_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("reset_email")
    if not email:
        flash("No active password reset session. Please request a new OTP.", "warning")
        return redirect(url_for("auth.forgot_password"))

    form = VerifyOTPForm()
    if request.method != "POST":
        return render_template("auth/verify_otp.html", form=form, email=email)

    otp_input = (form.otp.data or request.form.get("otp", "")).strip()
    expires_str = session.get("reset_otp_expires")
    expired = True
    if expires_str:
        try:
            expired = datetime.now(timezone.utc) > datetime.fromisoformat(expires_str)
        except ValueError:
            expired = True
    if expired:
        flash("The OTP has expired. Please request a new password reset code.", "danger")
        return redirect(url_for("auth.forgot_password"))

    session_hash = session.get("reset_otp_hash")
    if not session_hash or not check_password_hash(session_hash, otp_input):
        flash("Invalid OTP code.", "danger")
        return render_template("auth/verify_otp.html", form=form, email=email), 400

    session["otp_verified"] = True
    flash("OTP verified successfully.", "success")
    return redirect(url_for("auth.reset_password"))


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")
    verified = session.get("otp_verified", False)
    if not email or not verified:
        flash("You must verify an OTP before resetting your password.", "warning")
        return redirect(url_for("auth.forgot_password"))

    form = ResetPasswordForm()
    if request.method != "POST":
        return render_template("auth/reset_password.html", form=form, email=email)

    new_password = form.new_password.data or request.form.get("new_password", "")
    if len(new_password) < 6:
        flash("Password must be at least 6 characters long.", "danger")
        return render_template("auth/reset_password.html", form=form, email=email), 400

    _account_type, record = find_account_by_email(email)
    if not record:
        flash("User account not found.", "danger")
        return redirect(url_for("auth.login"))

    try:
        record.set_password(new_password)
        db.session.commit()
        session.pop("reset_email", None)
        session.pop("reset_otp_hash", None)
        session.pop("reset_otp_expires", None)
        session.pop("otp_verified", None)
        otp_storage.pop(email, None)
        flash("Your password has been reset successfully.", "success")
        return redirect(url_for("auth.login"))
    except Exception as error:
        db.session.rollback()
        flash(f"An error occurred while resetting password: {error}", "danger")
        return render_template("auth/reset_password.html", form=form, email=email), 500


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup_disabled():
    if request.is_json:
        return jsonify(
            {"message": "Open registration is disabled. Accounts are provisioned by administrators."}
        ), 403
    flash("Public self-registration is disabled.", "info")
    return redirect(url_for("auth.login"))
