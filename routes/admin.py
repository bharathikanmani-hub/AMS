"""Admin Blueprint for AttendAI.

Provides administrative management for:
- Dashboard metrics and analytics
- Department, User (Faculty/HOD/Student), Section, Subject, Classroom management
- Timetable scheduling and faculty-subject mapping
- Attendance overview, session inspection, and logs
- Report exports (CSV, Excel, PDF)
- System settings and Low Attendance notification alerts
"""

import csv
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
import io
import os
import smtplib

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import distinct, func, or_
from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Classroom,
    Department,
    FacultySubjectMapping,
    Notification,
    Section,
    Student,
    Subject,
    SystemSetting,
    Timetable,
    User,
)

# Optional export libraries
try:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# Access Control Decorator
# ---------------------------------------------------------------------------


def admin_required(f):
    """Ensure the user is authenticated and possesses the 'admin' role."""

    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if getattr(current_user, "role", "") != "admin":
            flash("Access denied. Administrator privileges required.", "danger")
            role = getattr(current_user, "role", "")
            if role == "hod":
                return redirect(url_for("hod.dashboard"))
            elif role == "faculty":
                return redirect(url_for("faculty.dashboard"))
            elif role == "student":
                return redirect(url_for("student.dashboard"))
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def log_audit(action: str, target_type: str = None, target_id=None, details: str = None) -> None:
    """Record an administrative change in the AuditLog table."""
    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        ip_addr = request.remote_addr if request else None

        entry = AuditLog()
        if hasattr(entry, "user_id"):
            entry.user_id = user_id
        if hasattr(entry, "action"):
            entry.action = action
        if hasattr(entry, "target_type"):
            entry.target_type = target_type
        elif hasattr(entry, "entity_type"):
            entry.entity_type = target_type
        if hasattr(entry, "target_id"):
            entry.target_id = str(target_id) if target_id is not None else None
        elif hasattr(entry, "entity_id"):
            entry.entity_id = target_id
        if hasattr(entry, "details"):
            entry.details = details
        elif hasattr(entry, "description"):
            entry.description = details
        if hasattr(entry, "ip_address"):
            entry.ip_address = ip_addr
        if hasattr(entry, "timestamp"):
            entry.timestamp = datetime.now(timezone.utc)
        elif hasattr(entry, "created_at"):
            entry.created_at = datetime.now(timezone.utc)

        db.session.add(entry)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"Failed to record audit log: {exc}")


def get_system_setting(key: str, default: str = "") -> str:
    """Retrieve system setting value by key."""
    try:
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting and setting.value:
            return setting.value
    except Exception:
        pass
    return default


def set_system_setting(key: str, value: str, description: str = "") -> None:
    """Upsert a system setting value."""
    setting = SystemSetting.query.filter_by(key=key).first()
    if setting:
        setting.value = value
        if description and hasattr(setting, "description"):
            setting.description = description
    else:
        setting = SystemSetting(key=key, value=value)
        if description and hasattr(setting, "description"):
            setting.description = description
        db.session.add(setting)


def get_user_display_name(user) -> str:
    """Safely obtain user name or email."""
    if not user:
        return "N/A"
    return getattr(user, "name", None) or getattr(user, "full_name", None) or getattr(user, "email", "N/A")


def set_user_password(user, password: str) -> None:
    """Hash and set user password with werkzeug."""
    hashed = generate_password_hash(password)
    if hasattr(user, "set_password") and callable(user.set_password):
        user.set_password(password)
    if hasattr(user, "password_hash"):
        user.password_hash = hashed
    if hasattr(user, "password"):
        user.password = hashed


# ---------------------------------------------------------------------------
# 1. Dashboard
# ---------------------------------------------------------------------------


@admin_bp.route("/")
@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    """Main administrator dashboard with high-level statistics and summaries."""
    today = date.today()

    total_departments = Department.query.count()
    total_students = Student.query.count()
    total_faculty = User.query.filter(User.role.in_(["faculty", "hod"])).count()
    active_sessions_today = AttendanceSession.query.filter(
        AttendanceSession.date == today
    ).count()

    # Overall College-wide Attendance Calculation
    total_records = AttendanceRecord.query.count()
    present_records = AttendanceRecord.query.filter(
        func.lower(AttendanceRecord.status) == "present"
    ).count()
    college_attendance_pct = (
        round((present_records / total_records * 100), 1) if total_records > 0 else 0.0
    )

    # Department-wise comparison
    departments = Department.query.filter_by(is_active=True).all()
    department_stats = []
    for dept in departments:
        dept_student_count = Student.query.filter_by(department_id=dept.id).count()

        # Query records belonging to sessions of subjects in this department
        dept_records_query = (
            db.session.query(AttendanceRecord)
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .join(Subject, AttendanceSession.subject_id == Subject.id)
            .filter(Subject.department_id == dept.id)
        )
        dept_total = dept_records_query.count()
        dept_present = dept_records_query.filter(
            func.lower(AttendanceRecord.status) == "present"
        ).count()
        dept_pct = (
            round((dept_present / dept_total * 100), 1) if dept_total > 0 else 0.0
        )

        department_stats.append(
            {
                "id": dept.id,
                "name": dept.name,
                "code": dept.code,
                "student_count": dept_student_count,
                "total_records": dept_total,
                "attendance_percentage": dept_pct,
            }
        )

    # Recent activity
    recent_sessions = (
        AttendanceSession.query.order_by(AttendanceSession.id.desc()).limit(5).all()
    )
    recent_logs = (
        AuditLog.query.order_by(AuditLog.id.desc()).limit(8).all()
    )

    stats = {
        "total_departments": total_departments,
        "total_students": total_students,
        "total_faculty": total_faculty,
        "active_sessions_today": active_sessions_today,
        "college_attendance_pct": college_attendance_pct,
        "total_records": total_records,
        "present_records": present_records,
    }

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        department_stats=department_stats,
        recent_sessions=recent_sessions,
        recent_logs=recent_logs,
    )


# ---------------------------------------------------------------------------
# 2. Department Management
# ---------------------------------------------------------------------------


@admin_bp.route("/departments", methods=["GET"])
@admin_required
def departments():
    """List departments with search and pagination."""
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()

    query = Department.query
    if q:
        query = query.filter(
            or_(
                Department.name.ilike(f"%{q}%"),
                Department.code.ilike(f"%{q}%"),
            )
        )

    pagination = query.order_by(Department.name.asc()).paginate(
        page=page, per_page=20, error_out=False
    )

    return render_template(
        "admin/departments.html",
        pagination=pagination,
        departments=pagination.items,
        search_query=q,
    )


@admin_bp.route("/departments/add", methods=["GET", "POST"])
@admin_required
def department_add():
    """Add a new academic department."""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        description = request.form.get("description", "").strip()

        if not name or not code:
            flash("Department name and code are required.", "danger")
            return render_template("admin/department_form.html", action="add", department=None), 400

        existing = Department.query.filter_by(code=code).first()
        if existing:
            flash(f"Department with code '{code}' already exists.", "danger")
            return render_template("admin/department_form.html", action="add", department=None), 400

        try:
            dept = Department(name=name, code=code, is_active=True)
            if hasattr(dept, "description") and description:
                dept.description = description
            db.session.add(dept)
            db.session.commit()

            log_audit("CREATE_DEPARTMENT", "Department", dept.id, f"Created department '{name}' ({code})")
            flash(f"Department '{name}' added successfully.", "success")
            return redirect(url_for("admin.departments"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to add department: {str(exc)}", "danger")
            return render_template("admin/department_form.html", action="add", department=None), 500

    return render_template("admin/department_form.html", action="add", department=None)


@admin_bp.route("/departments/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def department_edit(id: int):
    """Edit an existing department."""
    dept = Department.query.get_or_404(id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        description = request.form.get("description", "").strip()

        if not name or not code:
            flash("Department name and code are required.", "danger")
            return render_template("admin/department_form.html", action="edit", department=dept), 400

        existing = Department.query.filter(Department.code == code, Department.id != id).first()
        if existing:
            flash(f"Another department with code '{code}' already exists.", "danger")
            return render_template("admin/department_form.html", action="edit", department=dept), 400

        try:
            dept.name = name
            dept.code = code
            if hasattr(dept, "description"):
                dept.description = description
            db.session.commit()

            log_audit("UPDATE_DEPARTMENT", "Department", dept.id, f"Updated department '{name}' ({code})")
            flash(f"Department '{name}' updated successfully.", "success")
            return redirect(url_for("admin.departments"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update department: {str(exc)}", "danger")
            return render_template("admin/department_form.html", action="edit", department=dept), 500

    return render_template("admin/department_form.html", action="edit", department=dept)


@admin_bp.route("/departments/<int:id>/toggle", methods=["POST"])
@admin_required
def department_toggle(id: int):
    """Toggle department active/inactive status."""
    dept = Department.query.get_or_404(id)
    try:
        dept.is_active = not getattr(dept, "is_active", True)
        db.session.commit()

        status_text = "activated" if dept.is_active else "deactivated"
        log_audit("TOGGLE_DEPARTMENT", "Department", dept.id, f"Department '{dept.name}' {status_text}")
        flash(f"Department '{dept.name}' has been {status_text}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to update department status: {str(exc)}", "danger")

    return redirect(url_for("admin.departments"))


# ---------------------------------------------------------------------------
# 3. User Management
# ---------------------------------------------------------------------------


@admin_bp.route("/users", methods=["GET"])
@admin_required
def users():
    """List users with role filter, department filter, search, and pagination."""
    page = request.args.get("page", 1, type=int)
    role = request.args.get("role", "").strip().lower()
    dept_id = request.args.get("department_id", type=int)
    q = request.args.get("q", "").strip()

    query = User.query

    if role and role != "all":
        query = query.filter(User.role == role)

    if dept_id:
        query = query.filter(User.department_id == dept_id)

    if q:
        query = query.filter(
            or_(
                User.email.ilike(f"%{q}%"),
                User.name.ilike(f"%{q}%") if hasattr(User, "name") else False,
            )
        )

    pagination = query.order_by(User.id.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    return render_template(
        "admin/users.html",
        pagination=pagination,
        users=pagination.items,
        departments=departments,
        selected_role=role,
        selected_dept=dept_id,
        search_query=q,
    )


@admin_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def user_add():
    """Add a new user (admin, hod, faculty, or student)."""
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "").strip().lower()
        password = request.form.get("password", "")
        department_id = request.form.get("department_id", type=int)

        if not name or not email or not role or not password:
            flash("Name, email, role, and password are required.", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="add",
                    user=None,
                    departments=departments,
                    sections=sections,
                ),
                400,
            )

        if role not in ("admin", "hod", "faculty", "student"):
            flash("Invalid role selected.", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="add",
                    user=None,
                    departments=departments,
                    sections=sections,
                ),
                400,
            )

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="add",
                    user=None,
                    departments=departments,
                    sections=sections,
                ),
                400,
            )

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash(f"User with email '{email}' already exists.", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="add",
                    user=None,
                    departments=departments,
                    sections=sections,
                ),
                400,
            )

        # Student specific validation
        roll_number = request.form.get("roll_number", "").strip().upper()
        section_id = request.form.get("section_id", type=int)
        academic_year = request.form.get("academic_year", "").strip()

        if role == "student":
            if not roll_number:
                flash("Roll number is required for students.", "danger")
                return (
                    render_template(
                        "admin/user_form.html",
                        action="add",
                        user=None,
                        departments=departments,
                        sections=sections,
                    ),
                    400,
                )
            existing_student = Student.query.filter_by(roll_number=roll_number).first()
            if existing_student:
                flash(f"Student with roll number '{roll_number}' already exists.", "danger")
                return (
                    render_template(
                        "admin/user_form.html",
                        action="add",
                        user=None,
                        departments=departments,
                        sections=sections,
                    ),
                    400,
                )

        try:
            user = User(
                email=email,
                role=role,
                department_id=department_id if department_id else None,
                is_active=True,
            )
            if hasattr(user, "name"):
                user.name = name
            if hasattr(user, "full_name"):
                user.full_name = name

            set_user_password(user, password)
            db.session.add(user)
            db.session.flush()

            if role == "student":
                student = Student(
                    user_id=user.id,
                    roll_number=roll_number,
                    department_id=department_id,
                    section_id=section_id if section_id else None,
                )
                if hasattr(student, "academic_year") and academic_year:
                    student.academic_year = academic_year
                if hasattr(student, "name"):
                    student.name = name
                db.session.add(student)

            db.session.commit()

            log_audit("CREATE_USER", "User", user.id, f"Created {role} '{name}' ({email})")
            flash(f"User '{name}' created successfully.", "success")
            return redirect(url_for("admin.users"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to create user: {str(exc)}", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="add",
                    user=None,
                    departments=departments,
                    sections=sections,
                ),
                500,
            )

    return render_template(
        "admin/user_form.html",
        action="add",
        user=None,
        departments=departments,
        sections=sections,
    )


@admin_bp.route("/users/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(id: int):
    """Edit user details and associated student profile if applicable."""
    user = User.query.get_or_404(id)
    student = Student.query.filter_by(user_id=user.id).first()
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "").strip().lower()
        department_id = request.form.get("department_id", type=int)

        if not name or not email or not role:
            flash("Name, email, and role are required.", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="edit",
                    user=user,
                    student=student,
                    departments=departments,
                    sections=sections,
                ),
                400,
            )

        existing = User.query.filter(User.email == email, User.id != user.id).first()
        if existing:
            flash(f"Another user already has the email '{email}'.", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="edit",
                    user=user,
                    student=student,
                    departments=departments,
                    sections=sections,
                ),
                400,
            )

        try:
            if hasattr(user, "name"):
                user.name = name
            if hasattr(user, "full_name"):
                user.full_name = name
            user.email = email
            user.role = role
            user.department_id = department_id if department_id else None

            if role == "student":
                roll_number = request.form.get("roll_number", "").strip().upper()
                section_id = request.form.get("section_id", type=int)
                academic_year = request.form.get("academic_year", "").strip()

                if not roll_number:
                    flash("Roll number is required for students.", "danger")
                    return (
                        render_template(
                            "admin/user_form.html",
                            action="edit",
                            user=user,
                            student=student,
                            departments=departments,
                            sections=sections,
                        ),
                        400,
                    )

                if student:
                    student.roll_number = roll_number
                    student.department_id = department_id
                    student.section_id = section_id if section_id else None
                    if hasattr(student, "academic_year") and academic_year:
                        student.academic_year = academic_year
                else:
                    student = Student(
                        user_id=user.id,
                        roll_number=roll_number,
                        department_id=department_id,
                        section_id=section_id if section_id else None,
                    )
                    if hasattr(student, "academic_year") and academic_year:
                        student.academic_year = academic_year
                    db.session.add(student)

            db.session.commit()

            log_audit("UPDATE_USER", "User", user.id, f"Updated user '{name}' ({email})")
            flash(f"User '{name}' updated successfully.", "success")
            return redirect(url_for("admin.users"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update user: {str(exc)}", "danger")
            return (
                render_template(
                    "admin/user_form.html",
                    action="edit",
                    user=user,
                    student=student,
                    departments=departments,
                    sections=sections,
                ),
                500,
            )

    return render_template(
        "admin/user_form.html",
        action="edit",
        user=user,
        student=student,
        departments=departments,
        sections=sections,
    )


@admin_bp.route("/users/<int:id>/toggle", methods=["POST"])
@admin_required
def user_toggle(id: int):
    """Toggle user active/inactive status."""
    if id == current_user.id:
        flash("You cannot deactivate your own administrative account.", "danger")
        return redirect(url_for("admin.users"))

    user = User.query.get_or_404(id)
    try:
        user.is_active = not getattr(user, "is_active", True)
        db.session.commit()

        status_text = "activated" if user.is_active else "deactivated"
        log_audit("TOGGLE_USER", "User", user.id, f"User '{user.email}' {status_text}")
        flash(f"User '{user.email}' has been {status_text}.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to update user status: {str(exc)}", "danger")

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:id>/reset-password", methods=["POST"])
@admin_required
def user_reset_password(id: int):
    """Directly set a new password for a user from admin portal."""
    user = User.query.get_or_404(id)
    new_password = request.form.get("new_password", "").strip()

    if not new_password or len(new_password) < 6:
        flash("New password must be at least 6 characters long.", "danger")
        return redirect(url_for("admin.users"))

    try:
        set_user_password(user, new_password)
        db.session.commit()

        log_audit("ADMIN_RESET_PASSWORD", "User", user.id, f"Password reset by admin for {user.email}")
        flash(f"Password for user '{user.email}' has been reset successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to reset password: {str(exc)}", "danger")

    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# 4. Section Management
# ---------------------------------------------------------------------------


@admin_bp.route("/sections", methods=["GET"])
@admin_required
def sections():
    """List sections with department and semester filters."""
    page = request.args.get("page", 1, type=int)
    dept_id = request.args.get("department_id", type=int)
    semester = request.args.get("semester", type=int)
    q = request.args.get("q", "").strip()

    query = Section.query
    if dept_id:
        query = query.filter(Section.department_id == dept_id)
    if semester:
        query = query.filter(Section.semester == semester)
    if q:
        query = query.filter(Section.name.ilike(f"%{q}%"))

    pagination = query.order_by(Section.name.asc()).paginate(
        page=page, per_page=20, error_out=False
    )
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    return render_template(
        "admin/sections.html",
        pagination=pagination,
        sections=pagination.items,
        departments=departments,
        selected_dept=dept_id,
        selected_semester=semester,
        search_query=q,
    )


@admin_bp.route("/sections/add", methods=["GET", "POST"])
@admin_required
def section_add():
    """Add a new section."""
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip().upper()
        department_id = request.form.get("department_id", type=int)
        semester = request.form.get("semester", type=int)
        academic_year = request.form.get("academic_year", "").strip()

        if not name or not department_id:
            flash("Section name and department are required.", "danger")
            return render_template("admin/section_form.html", action="add", section=None, departments=departments), 400

        try:
            sec = Section(
                name=name,
                department_id=department_id,
                semester=semester if semester else None,
            )
            if hasattr(sec, "academic_year") and academic_year:
                sec.academic_year = academic_year
            if hasattr(sec, "is_active"):
                sec.is_active = True

            db.session.add(sec)
            db.session.commit()

            log_audit("CREATE_SECTION", "Section", sec.id, f"Created section '{name}'")
            flash(f"Section '{name}' added successfully.", "success")
            return redirect(url_for("admin.sections"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to add section: {str(exc)}", "danger")
            return render_template("admin/section_form.html", action="add", section=None, departments=departments), 500

    return render_template("admin/section_form.html", action="add", section=None, departments=departments)


@admin_bp.route("/sections/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def section_edit(id: int):
    """Edit section details."""
    sec = Section.query.get_or_404(id)
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip().upper()
        department_id = request.form.get("department_id", type=int)
        semester = request.form.get("semester", type=int)
        academic_year = request.form.get("academic_year", "").strip()

        if not name or not department_id:
            flash("Section name and department are required.", "danger")
            return render_template("admin/section_form.html", action="edit", section=sec, departments=departments), 400

        try:
            sec.name = name
            sec.department_id = department_id
            sec.semester = semester if semester else None
            if hasattr(sec, "academic_year"):
                sec.academic_year = academic_year

            db.session.commit()

            log_audit("UPDATE_SECTION", "Section", sec.id, f"Updated section '{name}'")
            flash(f"Section '{name}' updated successfully.", "success")
            return redirect(url_for("admin.sections"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update section: {str(exc)}", "danger")
            return render_template("admin/section_form.html", action="edit", section=sec, departments=departments), 500

    return render_template("admin/section_form.html", action="edit", section=sec, departments=departments)


@admin_bp.route("/sections/<int:id>/toggle", methods=["POST"])
@admin_required
def section_toggle(id: int):
    """Toggle section status if supported."""
    sec = Section.query.get_or_404(id)
    if hasattr(sec, "is_active"):
        try:
            sec.is_active = not sec.is_active
            db.session.commit()
            status = "activated" if sec.is_active else "deactivated"
            log_audit("TOGGLE_SECTION", "Section", sec.id, f"Section '{sec.name}' {status}")
            flash(f"Section '{sec.name}' {status}.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update section: {str(exc)}", "danger")
    return redirect(url_for("admin.sections"))


# ---------------------------------------------------------------------------
# 5. Subject Management
# ---------------------------------------------------------------------------


@admin_bp.route("/subjects", methods=["GET"])
@admin_required
def subjects():
    """List subjects with department, semester, and code/name search."""
    page = request.args.get("page", 1, type=int)
    dept_id = request.args.get("department_id", type=int)
    semester = request.args.get("semester", type=int)
    q = request.args.get("q", "").strip()

    query = Subject.query
    if dept_id:
        query = query.filter(Subject.department_id == dept_id)
    if semester:
        query = query.filter(Subject.semester == semester)
    if q:
        query = query.filter(
            or_(
                Subject.name.ilike(f"%{q}%"),
                Subject.code.ilike(f"%{q}%"),
            )
        )

    pagination = query.order_by(Subject.code.asc()).paginate(
        page=page, per_page=20, error_out=False
    )
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    return render_template(
        "admin/subjects.html",
        pagination=pagination,
        subjects=pagination.items,
        departments=departments,
        selected_dept=dept_id,
        selected_semester=semester,
        search_query=q,
    )


@admin_bp.route("/subjects/add", methods=["GET", "POST"])
@admin_required
def subject_add():
    """Add a new subject."""
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        department_id = request.form.get("department_id", type=int)
        semester = request.form.get("semester", type=int)
        credits = request.form.get("credits", type=int)

        if not name or not code or not department_id:
            flash("Subject name, code, and department are required.", "danger")
            return render_template("admin/subject_form.html", action="add", subject=None, departments=departments), 400

        existing = Subject.query.filter_by(code=code).first()
        if existing:
            flash(f"Subject with code '{code}' already exists.", "danger")
            return render_template("admin/subject_form.html", action="add", subject=None, departments=departments), 400

        try:
            sub = Subject(
                name=name,
                code=code,
                department_id=department_id,
                semester=semester if semester else 1,
            )
            if hasattr(sub, "credits") and credits is not None:
                sub.credits = credits
            if hasattr(sub, "is_active"):
                sub.is_active = True

            db.session.add(sub)
            db.session.commit()

            log_audit("CREATE_SUBJECT", "Subject", sub.id, f"Created subject '{name}' ({code})")
            flash(f"Subject '{name}' ({code}) added successfully.", "success")
            return redirect(url_for("admin.subjects"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to add subject: {str(exc)}", "danger")
            return render_template("admin/subject_form.html", action="add", subject=None, departments=departments), 500

    return render_template("admin/subject_form.html", action="add", subject=None, departments=departments)


@admin_bp.route("/subjects/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def subject_edit(id: int):
    """Edit subject details."""
    sub = Subject.query.get_or_404(id)
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        department_id = request.form.get("department_id", type=int)
        semester = request.form.get("semester", type=int)
        credits = request.form.get("credits", type=int)

        if not name or not code or not department_id:
            flash("Subject name, code, and department are required.", "danger")
            return render_template("admin/subject_form.html", action="edit", subject=sub, departments=departments), 400

        existing = Subject.query.filter(Subject.code == code, Subject.id != id).first()
        if existing:
            flash(f"Another subject with code '{code}' already exists.", "danger")
            return render_template("admin/subject_form.html", action="edit", subject=sub, departments=departments), 400

        try:
            sub.name = name
            sub.code = code
            sub.department_id = department_id
            sub.semester = semester if semester else 1
            if hasattr(sub, "credits") and credits is not None:
                sub.credits = credits

            db.session.commit()

            log_audit("UPDATE_SUBJECT", "Subject", sub.id, f"Updated subject '{name}' ({code})")
            flash(f"Subject '{name}' ({code}) updated successfully.", "success")
            return redirect(url_for("admin.subjects"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update subject: {str(exc)}", "danger")
            return render_template("admin/subject_form.html", action="edit", subject=sub, departments=departments), 500

    return render_template("admin/subject_form.html", action="edit", subject=sub, departments=departments)


@admin_bp.route("/subjects/<int:id>/toggle", methods=["POST"])
@admin_required
def subject_toggle(id: int):
    """Toggle subject active status if column is present."""
    sub = Subject.query.get_or_404(id)
    if hasattr(sub, "is_active"):
        try:
            sub.is_active = not sub.is_active
            db.session.commit()
            status = "activated" if sub.is_active else "deactivated"
            log_audit("TOGGLE_SUBJECT", "Subject", sub.id, f"Subject '{sub.name}' {status}")
            flash(f"Subject '{sub.name}' has been {status}.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to toggle subject: {str(exc)}", "danger")
    return redirect(url_for("admin.subjects"))


# ---------------------------------------------------------------------------
# 6. Classroom Management
# ---------------------------------------------------------------------------


@admin_bp.route("/classrooms", methods=["GET"])
@admin_required
def classrooms():
    """List classrooms with search and pagination."""
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()

    query = Classroom.query
    if q:
        query = query.filter(
            or_(
                Classroom.room_number.ilike(f"%{q}%") if hasattr(Classroom, "room_number") else False,
                Classroom.name.ilike(f"%{q}%") if hasattr(Classroom, "name") else False,
                Classroom.building.ilike(f"%{q}%") if hasattr(Classroom, "building") else False,
            )
        )

    pagination = query.order_by(Classroom.id.asc()).paginate(
        page=page, per_page=20, error_out=False
    )

    return render_template(
        "admin/classrooms.html",
        pagination=pagination,
        classrooms=pagination.items,
        search_query=q,
    )


@admin_bp.route("/classrooms/add", methods=["GET", "POST"])
@admin_required
def classroom_add():
    """Add a new classroom."""
    if request.method == "POST":
        room_number = request.form.get("room_number", "").strip().upper()
        capacity = request.form.get("capacity", type=int)
        building = request.form.get("building", "").strip()
        floor = request.form.get("floor", "").strip()

        if not room_number:
            flash("Room number / name is required.", "danger")
            return render_template("admin/classroom_form.html", action="add", classroom=None), 400

        try:
            cls_room = Classroom()
            if hasattr(cls_room, "room_number"):
                cls_room.room_number = room_number
            if hasattr(cls_room, "name"):
                cls_room.name = room_number
            if hasattr(cls_room, "capacity") and capacity:
                cls_room.capacity = capacity
            if hasattr(cls_room, "building") and building:
                cls_room.building = building
            if hasattr(cls_room, "floor") and floor:
                cls_room.floor = floor
            if hasattr(cls_room, "is_active"):
                cls_room.is_active = True

            db.session.add(cls_room)
            db.session.commit()

            log_audit("CREATE_CLASSROOM", "Classroom", cls_room.id, f"Created classroom '{room_number}'")
            flash(f"Classroom '{room_number}' added successfully.", "success")
            return redirect(url_for("admin.classrooms"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to add classroom: {str(exc)}", "danger")
            return render_template("admin/classroom_form.html", action="add", classroom=None), 500

    return render_template("admin/classroom_form.html", action="add", classroom=None)


@admin_bp.route("/classrooms/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def classroom_edit(id: int):
    """Edit classroom details."""
    cls_room = Classroom.query.get_or_404(id)

    if request.method == "POST":
        room_number = request.form.get("room_number", "").strip().upper()
        capacity = request.form.get("capacity", type=int)
        building = request.form.get("building", "").strip()
        floor = request.form.get("floor", "").strip()

        if not room_number:
            flash("Room number / name is required.", "danger")
            return render_template("admin/classroom_form.html", action="edit", classroom=cls_room), 400

        try:
            if hasattr(cls_room, "room_number"):
                cls_room.room_number = room_number
            if hasattr(cls_room, "name"):
                cls_room.name = room_number
            if hasattr(cls_room, "capacity") and capacity:
                cls_room.capacity = capacity
            if hasattr(cls_room, "building"):
                cls_room.building = building
            if hasattr(cls_room, "floor"):
                cls_room.floor = floor

            db.session.commit()

            log_audit("UPDATE_CLASSROOM", "Classroom", cls_room.id, f"Updated classroom '{room_number}'")
            flash(f"Classroom '{room_number}' updated successfully.", "success")
            return redirect(url_for("admin.classrooms"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update classroom: {str(exc)}", "danger")
            return render_template("admin/classroom_form.html", action="edit", classroom=cls_room), 500

    return render_template("admin/classroom_form.html", action="edit", classroom=cls_room)


@admin_bp.route("/classrooms/<int:id>/toggle", methods=["POST"])
@admin_required
def classroom_toggle(id: int):
    """Toggle classroom active status if present."""
    cls_room = Classroom.query.get_or_404(id)
    if hasattr(cls_room, "is_active"):
        try:
            cls_room.is_active = not cls_room.is_active
            db.session.commit()
            status = "activated" if cls_room.is_active else "deactivated"
            room_title = getattr(cls_room, "room_number", None) or getattr(cls_room, "name", str(id))
            log_audit("TOGGLE_CLASSROOM", "Classroom", cls_room.id, f"Classroom '{room_title}' {status}")
            flash(f"Classroom '{room_title}' has been {status}.", "success")
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update classroom: {str(exc)}", "danger")
    return redirect(url_for("admin.classrooms"))


# ---------------------------------------------------------------------------
# 7. Timetable Management
# ---------------------------------------------------------------------------


@admin_bp.route("/timetable", methods=["GET"])
@admin_required
def timetable():
    """View timetable with department, section, and day filters."""
    dept_id = request.args.get("department_id", type=int)
    sec_id = request.args.get("section_id", type=int)
    day = request.args.get("day", "").strip()

    query = Timetable.query

    if dept_id:
        query = query.filter(Timetable.department_id == dept_id)
    if sec_id:
        query = query.filter(Timetable.section_id == sec_id)
    if day:
        query = query.filter(Timetable.day_of_week == day)

    entries = query.order_by(Timetable.day_of_week.asc(), Timetable.start_time.asc()).all()

    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    return render_template(
        "admin/timetable.html",
        entries=entries,
        departments=departments,
        sections=sections,
        days=days,
        selected_dept=dept_id,
        selected_sec=sec_id,
        selected_day=day,
    )


@admin_bp.route("/timetable/add", methods=["GET", "POST"])
@admin_required
def timetable_add():
    """Add a timetable schedule slot and ensure faculty-subject mapping."""
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    faculty_members = (
        User.query.filter(User.role.in_(["faculty", "hod"]), User.is_active == True)
        .order_by(User.name.asc() if hasattr(User, "name") else User.email.asc())
        .all()
    )
    classrooms = Classroom.query.order_by(Classroom.id.asc()).all()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    if request.method == "POST":
        department_id = request.form.get("department_id", type=int)
        section_id = request.form.get("section_id", type=int)
        subject_id = request.form.get("subject_id", type=int)
        faculty_id = request.form.get("faculty_id", type=int)
        classroom_id = request.form.get("classroom_id", type=int)
        day_of_week = request.form.get("day_of_week", "").strip()
        start_time_str = request.form.get("start_time", "").strip()
        end_time_str = request.form.get("end_time", "").strip()
        academic_year = request.form.get("academic_year", "").strip()

        if not (department_id and section_id and subject_id and faculty_id and day_of_week and start_time_str and end_time_str):
            flash("All timetable fields marked as required must be filled.", "danger")
            return (
                render_template(
                    "admin/timetable_form.html",
                    action="add",
                    entry=None,
                    departments=departments,
                    sections=sections,
                    subjects=subjects,
                    faculty_members=faculty_members,
                    classrooms=classrooms,
                    days=days,
                ),
                400,
            )

        try:
            # Parse times
            start_parts = [int(p) for p in start_time_str.split(":")[:2]]
            end_parts = [int(p) for p in end_time_str.split(":")[:2]]
            start_t = time(hour=start_parts[0], minute=start_parts[1])
            end_t = time(hour=end_parts[0], minute=end_parts[1])

            # Ensure FacultySubjectMapping exists
            mapping = FacultySubjectMapping.query.filter_by(
                faculty_id=faculty_id,
                subject_id=subject_id,
                section_id=section_id,
            ).first()

            if not mapping:
                mapping = FacultySubjectMapping(
                    faculty_id=faculty_id,
                    subject_id=subject_id,
                    section_id=section_id,
                )
                if hasattr(mapping, "academic_year") and academic_year:
                    mapping.academic_year = academic_year
                db.session.add(mapping)
                db.session.flush()

            entry = Timetable(
                department_id=department_id,
                section_id=section_id,
                subject_id=subject_id,
                faculty_id=faculty_id,
                classroom_id=classroom_id if classroom_id else None,
                day_of_week=day_of_week,
                start_time=start_t,
                end_time=end_t,
            )
            if hasattr(entry, "mapping_id") and mapping:
                entry.mapping_id = mapping.id

            db.session.add(entry)
            db.session.commit()

            log_audit("CREATE_TIMETABLE", "Timetable", entry.id, f"Added slot for {day_of_week} {start_time_str}-{end_time_str}")
            flash("Timetable slot added successfully.", "success")
            return redirect(url_for("admin.timetable"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to add timetable entry: {str(exc)}", "danger")
            return (
                render_template(
                    "admin/timetable_form.html",
                    action="add",
                    entry=None,
                    departments=departments,
                    sections=sections,
                    subjects=subjects,
                    faculty_members=faculty_members,
                    classrooms=classrooms,
                    days=days,
                ),
                500,
            )

    return render_template(
        "admin/timetable_form.html",
        action="add",
        entry=None,
        departments=departments,
        sections=sections,
        subjects=subjects,
        faculty_members=faculty_members,
        classrooms=classrooms,
        days=days,
    )


@admin_bp.route("/timetable/<int:id>/edit", methods=["GET", "POST"])
@admin_required
def timetable_edit(id: int):
    """Edit an existing timetable entry."""
    entry = Timetable.query.get_or_404(id)
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    faculty_members = (
        User.query.filter(User.role.in_(["faculty", "hod"]), User.is_active == True)
        .order_by(User.name.asc() if hasattr(User, "name") else User.email.asc())
        .all()
    )
    classrooms = Classroom.query.order_by(Classroom.id.asc()).all()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    if request.method == "POST":
        department_id = request.form.get("department_id", type=int)
        section_id = request.form.get("section_id", type=int)
        subject_id = request.form.get("subject_id", type=int)
        faculty_id = request.form.get("faculty_id", type=int)
        classroom_id = request.form.get("classroom_id", type=int)
        day_of_week = request.form.get("day_of_week", "").strip()
        start_time_str = request.form.get("start_time", "").strip()
        end_time_str = request.form.get("end_time", "").strip()

        if not (department_id and section_id and subject_id and faculty_id and day_of_week and start_time_str and end_time_str):
            flash("All fields are required.", "danger")
            return (
                render_template(
                    "admin/timetable_form.html",
                    action="edit",
                    entry=entry,
                    departments=departments,
                    sections=sections,
                    subjects=subjects,
                    faculty_members=faculty_members,
                    classrooms=classrooms,
                    days=days,
                ),
                400,
            )

        try:
            start_parts = [int(p) for p in start_time_str.split(":")[:2]]
            end_parts = [int(p) for p in end_time_str.split(":")[:2]]
            start_t = time(hour=start_parts[0], minute=start_parts[1])
            end_t = time(hour=end_parts[0], minute=end_parts[1])

            entry.department_id = department_id
            entry.section_id = section_id
            entry.subject_id = subject_id
            entry.faculty_id = faculty_id
            entry.classroom_id = classroom_id if classroom_id else None
            entry.day_of_week = day_of_week
            entry.start_time = start_t
            entry.end_time = end_t

            db.session.commit()

            log_audit("UPDATE_TIMETABLE", "Timetable", entry.id, f"Updated slot {entry.id}")
            flash("Timetable entry updated successfully.", "success")
            return redirect(url_for("admin.timetable"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to update timetable: {str(exc)}", "danger")
            return (
                render_template(
                    "admin/timetable_form.html",
                    action="edit",
                    entry=entry,
                    departments=departments,
                    sections=sections,
                    subjects=subjects,
                    faculty_members=faculty_members,
                    classrooms=classrooms,
                    days=days,
                ),
                500,
            )

    return render_template(
        "admin/timetable_form.html",
        action="edit",
        entry=entry,
        departments=departments,
        sections=sections,
        subjects=subjects,
        faculty_members=faculty_members,
        classrooms=classrooms,
        days=days,
    )


@admin_bp.route("/timetable/<int:id>/delete", methods=["POST"])
@admin_required
def timetable_delete(id: int):
    """Delete a timetable schedule entry."""
    entry = Timetable.query.get_or_404(id)
    try:
        db.session.delete(entry)
        db.session.commit()

        log_audit("DELETE_TIMETABLE", "Timetable", id, f"Deleted timetable slot {id}")
        flash("Timetable entry deleted successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Failed to delete timetable entry: {str(exc)}", "danger")

    return redirect(url_for("admin.timetable"))


# ---------------------------------------------------------------------------
# 8. Attendance Overview & Sessions
# ---------------------------------------------------------------------------


@admin_bp.route("/attendance", methods=["GET"])
@admin_required
def attendance():
    """Comprehensive attendance view with multiple filter criteria and pagination."""
    page = request.args.get("page", 1, type=int)
    date_str = request.args.get("date", "").strip()
    dept_id = request.args.get("department_id", type=int)
    sec_id = request.args.get("section_id", type=int)
    sub_id = request.args.get("subject_id", type=int)
    status = request.args.get("status", "").strip()

    query = AttendanceRecord.query.join(
        AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id
    )

    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(AttendanceSession.date == target_date)
        except ValueError:
            pass

    if dept_id:
        query = query.join(Subject, AttendanceSession.subject_id == Subject.id).filter(
            Subject.department_id == dept_id
        )

    if sec_id:
        query = query.filter(AttendanceSession.section_id == sec_id)

    if sub_id:
        query = query.filter(AttendanceSession.subject_id == sub_id)

    if status:
        query = query.filter(func.lower(AttendanceRecord.status) == status.lower())

    pagination = query.order_by(AttendanceRecord.id.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()
    subjects = Subject.query.order_by(Subject.name.asc()).all()

    return render_template(
        "admin/attendance.html",
        pagination=pagination,
        records=pagination.items,
        departments=departments,
        sections=sections,
        subjects=subjects,
        selected_date=date_str,
        selected_dept=dept_id,
        selected_sec=sec_id,
        selected_sub=sub_id,
        selected_status=status,
    )


@admin_bp.route("/attendance/sessions", methods=["GET"])
@admin_required
def attendance_sessions():
    """List attendance sessions with filters and pagination."""
    page = request.args.get("page", 1, type=int)
    date_str = request.args.get("date", "").strip()
    faculty_id = request.args.get("faculty_id", type=int)
    sub_id = request.args.get("subject_id", type=int)
    sec_id = request.args.get("section_id", type=int)
    status = request.args.get("status", "").strip()

    query = AttendanceSession.query

    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter(AttendanceSession.date == target_date)
        except ValueError:
            pass

    if faculty_id:
        query = query.filter(AttendanceSession.faculty_id == faculty_id)

    if sub_id:
        query = query.filter(AttendanceSession.subject_id == sub_id)

    if sec_id:
        query = query.filter(AttendanceSession.section_id == sec_id)

    if status:
        query = query.filter(AttendanceSession.status == status)

    pagination = query.order_by(AttendanceSession.date.desc(), AttendanceSession.id.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    faculty_members = User.query.filter(User.role.in_(["faculty", "hod"])).all()
    subjects = Subject.query.order_by(Subject.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()

    return render_template(
        "admin/sessions.html",
        pagination=pagination,
        sessions=pagination.items,
        faculty_members=faculty_members,
        subjects=subjects,
        sections=sections,
        selected_date=date_str,
        selected_faculty=faculty_id,
        selected_sub=sub_id,
        selected_sec=sec_id,
        selected_status=status,
    )


@admin_bp.route("/attendance/session/<int:id>", methods=["GET"])
@admin_required
def attendance_session_detail(id: int):
    """View detailed attendance records and statistics for a specific session."""
    session_obj = AttendanceSession.query.get_or_404(id)
    records = AttendanceRecord.query.filter_by(session_id=id).all()

    total_records = len(records)
    present_count = sum(1 for r in records if (r.status or "").lower() == "present")
    absent_count = sum(1 for r in records if (r.status or "").lower() == "absent")
    late_count = sum(1 for r in records if (r.status or "").lower() == "late")
    attendance_pct = (
        round((present_count / total_records * 100), 1) if total_records > 0 else 0.0
    )

    summary = {
        "total": total_records,
        "present": present_count,
        "absent": absent_count,
        "late": late_count,
        "percentage": attendance_pct,
    }

    return render_template(
        "admin/session_detail.html",
        session=session_obj,
        records=records,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# 9. Reports & Exports
# ---------------------------------------------------------------------------


def get_filtered_attendance_data():
    """Common filtering helper for report queries and exports."""
    start_date_str = request.args.get("start_date", "").strip()
    end_date_str = request.args.get("end_date", "").strip()
    dept_id = request.args.get("department_id", type=int)
    sec_id = request.args.get("section_id", type=int)
    sub_id = request.args.get("subject_id", type=int)

    query = db.session.query(
        AttendanceRecord, AttendanceSession, Subject, Section, Student, User
    ).join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id
    ).join(Subject, AttendanceSession.subject_id == Subject.id
    ).join(Section, AttendanceSession.section_id == Section.id
    ).join(Student, AttendanceRecord.student_id == Student.id
    ).join(User, Student.user_id == User.id)

    if start_date_str:
        try:
            start_d = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            query = query.filter(AttendanceSession.date >= start_d)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_d = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            query = query.filter(AttendanceSession.date <= end_d)
        except ValueError:
            pass

    if dept_id:
        query = query.filter(Subject.department_id == dept_id)

    if sec_id:
        query = query.filter(AttendanceSession.section_id == sec_id)

    if sub_id:
        query = query.filter(AttendanceSession.subject_id == sub_id)

    return query.order_by(AttendanceSession.date.desc(), AttendanceRecord.id.desc()).all()


@admin_bp.route("/reports", methods=["GET"])
@admin_required
def reports():
    """Reports landing page with filtering options and preview summary."""
    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()
    subjects = Subject.query.order_by(Subject.name.asc()).all()

    # Calculate brief preview summary
    results = get_filtered_attendance_data()
    total_count = len(results)
    present_count = sum(1 for row in results if (row[0].status or "").lower() == "present")
    pct = round((present_count / total_count * 100), 1) if total_count > 0 else 0.0

    summary = {
        "total_records": total_count,
        "present_count": present_count,
        "absent_count": total_count - present_count,
        "average_percentage": pct,
    }

    return render_template(
        "admin/reports.html",
        departments=departments,
        sections=sections,
        subjects=subjects,
        summary=summary,
        selected_start=request.args.get("start_date", ""),
        selected_end=request.args.get("end_date", ""),
        selected_dept=request.args.get("department_id", type=int),
        selected_sec=request.args.get("section_id", type=int),
        selected_sub=request.args.get("subject_id", type=int),
    )


@admin_bp.route("/reports/export/csv", methods=["GET"])
@admin_required
def reports_export_csv():
    """Export filtered attendance records to CSV."""
    rows = get_filtered_attendance_data()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date",
        "Session ID",
        "Subject Code",
        "Subject Name",
        "Section",
        "Roll Number",
        "Student Name",
        "Status",
        "Marked Time",
        "Verification Method",
    ])

    for record, session_obj, subject, section, student, user in rows:
        marked_time = ""
        if hasattr(record, "timestamp") and record.timestamp:
            marked_time = record.timestamp.strftime("%H:%M:%S")
        elif hasattr(record, "marked_at") and record.marked_at:
            marked_time = record.marked_at.strftime("%H:%M:%S")

        method = getattr(record, "method", None) or getattr(record, "verification_method", "manual")
        writer.writerow([
            session_obj.date.strftime("%Y-%m-%d"),
            session_obj.id,
            subject.code,
            subject.name,
            section.name,
            student.roll_number,
            get_user_display_name(user),
            record.status,
            marked_time,
            method,
        ])

    csv_data = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"attendance_report_{timestamp}.csv"

    log_audit("EXPORT_REPORT_CSV", "AttendanceRecord", None, f"Exported {len(rows)} records to CSV")

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/reports/export/excel", methods=["GET"])
@admin_required
def reports_export_excel():
    """Export filtered attendance records to Excel spreadsheet."""
    if not OPENPYXL_AVAILABLE:
        flash("Excel generation library (openpyxl) is not available. Exporting as CSV instead.", "warning")
        return redirect(url_for("admin.reports_export_csv", **request.args))

    rows = get_filtered_attendance_data()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance Report"

    # Styling definitions
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    center_align = Alignment(horizontal="center", vertical="center")
    left_align = Alignment(horizontal="left", vertical="center")

    headers = [
        "Date",
        "Session ID",
        "Subject Code",
        "Subject Name",
        "Section",
        "Roll Number",
        "Student Name",
        "Status",
        "Time",
        "Method",
    ]

    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    for record, session_obj, subject, section, student, user in rows:
        marked_time = ""
        if hasattr(record, "timestamp") and record.timestamp:
            marked_time = record.timestamp.strftime("%H:%M:%S")
        elif hasattr(record, "marked_at") and record.marked_at:
            marked_time = record.marked_at.strftime("%H:%M:%S")

        method = getattr(record, "method", None) or getattr(record, "verification_method", "manual")
        ws.append([
            session_obj.date.strftime("%Y-%m-%d"),
            session_obj.id,
            subject.code,
            subject.name,
            section.name,
            student.roll_number,
            get_user_display_name(user),
            record.status,
            marked_time,
            method,
        ])

    # Auto-adjust column width
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"attendance_report_{timestamp}.xlsx"

    log_audit("EXPORT_REPORT_EXCEL", "AttendanceRecord", None, f"Exported {len(rows)} records to Excel")

    return Response(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@admin_bp.route("/reports/export/pdf", methods=["GET"])
@admin_required
def reports_export_pdf():
    """Export filtered attendance records to formatted PDF document."""
    if not REPORTLAB_AVAILABLE:
        flash("PDF generation library (reportlab) is not available. Exporting as CSV instead.", "warning")
        return redirect(url_for("admin.reports_export_csv", **request.args))

    rows = get_filtered_attendance_data()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    normal_style = styles["Normal"]

    elements = []
    elements.append(Paragraph("AttendAI - Attendance Report", title_style))
    elements.append(
        Paragraph(
            f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Total Records: {len(rows)}",
            normal_style,
        )
    )
    elements.append(Spacer(1, 15))

    table_data = [
        ["Date", "Subject", "Section", "Roll Number", "Student Name", "Status", "Time", "Method"]
    ]

    for record, session_obj, subject, section, student, user in rows[:500]:  # Limit to 500 rows for PDF stability
        marked_time = ""
        if hasattr(record, "timestamp") and record.timestamp:
            marked_time = record.timestamp.strftime("%H:%M")
        elif hasattr(record, "marked_at") and record.marked_at:
            marked_time = record.marked_at.strftime("%H:%M")

        method = getattr(record, "method", None) or getattr(record, "verification_method", "manual")
        table_data.append([
            session_obj.date.strftime("%Y-%m-%d"),
            f"{subject.code}",
            section.name,
            student.roll_number,
            get_user_display_name(user)[:20],
            record.status,
            marked_time,
            method,
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F9F9F9")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"attendance_report_{timestamp}.pdf"

    log_audit("EXPORT_REPORT_PDF", "AttendanceRecord", None, f"Exported {len(rows)} records to PDF")

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# 10. Settings Management
# ---------------------------------------------------------------------------


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    """System settings management (thresholds, academic year, SMTP)."""
    if request.method == "POST":
        try:
            fields = [
                "attendance_threshold",
                "low_attendance_threshold",
                "academic_year",
                "smtp_host",
                "smtp_port",
                "smtp_user",
                "smtp_password",
                "smtp_use_tls",
            ]
            for key in fields:
                val = request.form.get(key, "").strip()
                set_system_setting(key, val)

            db.session.commit()

            log_audit("UPDATE_SETTINGS", "SystemSetting", None, "Updated system settings")
            flash("System settings saved successfully.", "success")
            return redirect(url_for("admin.settings"))
        except Exception as exc:
            db.session.rollback()
            flash(f"Failed to save settings: {str(exc)}", "danger")

    # Load all settings
    all_settings = {s.key: s.value for s in SystemSetting.query.all()}
    settings_dict = {
        "attendance_threshold": all_settings.get("attendance_threshold", "75"),
        "low_attendance_threshold": all_settings.get("low_attendance_threshold", "65"),
        "academic_year": all_settings.get("academic_year", "2025-2026"),
        "smtp_host": all_settings.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": all_settings.get("smtp_port", "587"),
        "smtp_user": all_settings.get("smtp_user", ""),
        "smtp_password": all_settings.get("smtp_password", ""),
        "smtp_use_tls": all_settings.get("smtp_use_tls", "true"),
    }

    return render_template("admin/settings.html", settings=settings_dict)


# ---------------------------------------------------------------------------
# 11. Audit Log
# ---------------------------------------------------------------------------


@admin_bp.route("/audit-log", methods=["GET"])
@admin_required
def audit_log():
    """View system audit logs with filters and pagination."""
    page = request.args.get("page", 1, type=int)
    action_filter = request.args.get("action", "").strip()
    user_id_filter = request.args.get("user_id", type=int)
    date_filter = request.args.get("date", "").strip()

    query = AuditLog.query

    if action_filter:
        query = query.filter(AuditLog.action.ilike(f"%{action_filter}%"))

    if user_id_filter:
        query = query.filter(AuditLog.user_id == user_id_filter)

    if date_filter:
        try:
            target_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
            if hasattr(AuditLog, "timestamp"):
                query = query.filter(func.date(AuditLog.timestamp) == target_date)
            elif hasattr(AuditLog, "created_at"):
                query = query.filter(func.date(AuditLog.created_at) == target_date)
        except ValueError:
            pass

    pagination = query.order_by(AuditLog.id.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    users_list = User.query.order_by(User.email.asc()).all()

    return render_template(
        "admin/audit_log.html",
        pagination=pagination,
        logs=pagination.items,
        users=users_list,
        selected_action=action_filter,
        selected_user=user_id_filter,
        selected_date=date_filter,
    )


# ---------------------------------------------------------------------------
# 12. Low Attendance Alerts
# ---------------------------------------------------------------------------


def calculate_students_below_threshold(threshold: float, dept_id: int = None, sec_id: int = None):
    """Identify students whose overall attendance rate is below given threshold."""
    query = Student.query
    if dept_id:
        query = query.filter(Student.department_id == dept_id)
    if sec_id:
        query = query.filter(Student.section_id == sec_id)

    students = query.all()
    flagged = []

    for st in students:
        total = AttendanceRecord.query.filter_by(student_id=st.id).count()
        present = AttendanceRecord.query.filter(
            AttendanceRecord.student_id == st.id,
            func.lower(AttendanceRecord.status) == "present",
        ).count()

        percentage = round((present / total * 100), 1) if total > 0 else 0.0

        if total > 0 and percentage < threshold:
            user = User.query.get(st.user_id) if st.user_id else None
            flagged.append(
                {
                    "student": st,
                    "user": user,
                    "total_classes": total,
                    "attended_classes": present,
                    "percentage": percentage,
                }
            )

    return flagged


@admin_bp.route("/alerts", methods=["GET"])
@admin_required
def alerts():
    """Display students falling below the minimum attendance threshold."""
    threshold_str = get_system_setting("low_attendance_threshold", "75")
    try:
        threshold = float(request.args.get("threshold", threshold_str))
    except ValueError:
        threshold = 75.0

    dept_id = request.args.get("department_id", type=int)
    sec_id = request.args.get("section_id", type=int)

    flagged_students = calculate_students_below_threshold(threshold, dept_id, sec_id)

    departments = Department.query.filter_by(is_active=True).order_by(Department.name.asc()).all()
    sections = Section.query.order_by(Section.name.asc()).all()

    return render_template(
        "admin/alerts.html",
        flagged_students=flagged_students,
        threshold=threshold,
        departments=departments,
        sections=sections,
        selected_dept=dept_id,
        selected_sec=sec_id,
    )


@admin_bp.route("/alerts/send", methods=["POST"])
@admin_required
def alerts_send():
    """Send notifications and email warnings to low-attendance students."""
    threshold_str = get_system_setting("low_attendance_threshold", "75")
    try:
        threshold = float(request.form.get("threshold", threshold_str))
    except ValueError:
        threshold = 75.0

    dept_id = request.form.get("department_id", type=int)
    sec_id = request.form.get("section_id", type=int)

    flagged = calculate_students_below_threshold(threshold, dept_id, sec_id)

    if not flagged:
        flash("No students found below the specified attendance threshold.", "info")
        return redirect(url_for("admin.alerts"))

    # Attempt to load SMTP credentials
    smtp_host = get_system_setting("smtp_host", os.getenv("MAIL_SERVER", "smtp.gmail.com"))
    smtp_port = int(get_system_setting("smtp_port", os.getenv("MAIL_PORT", "587")))
    smtp_user = get_system_setting("smtp_user", os.getenv("MAIL_EMAIL", os.getenv("MAIL_USERNAME", "")))
    smtp_pwd = get_system_setting("smtp_password", os.getenv("MAIL_APP_PASSWORD", os.getenv("MAIL_PASSWORD", "")))

    smtp_available = bool(smtp_user and smtp_pwd)

    sent_count = 0
    in_app_count = 0

    for item in flagged:
        st = item["student"]
        usr = item["user"]
        pct = item["percentage"]

        if not usr:
            continue

        # In-app notification
        try:
            notif = Notification(
                user_id=usr.id,
                title="Low Attendance Warning",
                message=(
                    f"Warning: Your overall attendance is currently {pct}%, "
                    f"which is below the required {threshold}% threshold. "
                    f"Please contact your Head of Department immediately."
                ),
            )
            if hasattr(notif, "type"):
                notif.type = "warning"
            if hasattr(notif, "is_read"):
                notif.is_read = False
            db.session.add(notif)
            in_app_count += 1
        except Exception:
            pass

        # Email notification
        if smtp_available and usr.email:
            try:
                msg = EmailMessage()
                msg["Subject"] = "AttendAI - Low Attendance Warning Notice"
                msg["From"] = smtp_user
                msg["To"] = usr.email
                msg.set_content(
                    f"Dear {get_user_display_name(usr)},\n\n"
                    f"Your overall recorded attendance is currently {pct}%, which falls below "
                    f"the mandatory institutional threshold of {threshold}%.\n\n"
                    f"You have attended {item['attended_classes']} out of {item['total_classes']} scheduled classes.\n\n"
                    f"Please attend upcoming classes regularly and meet with your department advisor.\n\n"
                    f"Regards,\nAcademic Administration\nAttendAI System"
                )
                with smtplib.SMTP(smtp_host, smtp_port, timeout=5) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pwd)
                    server.send_message(msg)
                sent_count += 1
            except Exception as mail_err:
                print(f"Failed to send warning email to {usr.email}: {mail_err}")

    try:
        db.session.commit()
        log_audit(
            "SEND_LOW_ATTENDANCE_ALERTS",
            "Notification",
            None,
            f"Created {in_app_count} notifications, sent {sent_count} emails for threshold {threshold}%",
        )
        flash(
            f"Alerts processed: {in_app_count} in-app notification(s) created, {sent_count} email(s) dispatched.",
            "success",
        )
    except Exception as exc:
        db.session.rollback()
        flash(f"Error recording notifications: {str(exc)}", "danger")

    return redirect(url_for("admin.alerts"))
