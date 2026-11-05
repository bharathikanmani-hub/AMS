"""Admin API.  Prefix: /api/admin   (admin role only)

  GET  /overview                       dashboard counters
  GET  /users                          all users (+ student section, e-mail, pending approval)
  POST /users                          create a faculty/admin account  -> returns the new sign-in ID
  POST /users/<id>/active              enable / disable an account
  POST /users/<id>/approve | reject    decide a faculty/admin self-registration
  POST /users/<id>/email               change the e-mail of an account (needed for password-reset codes)
  GET  /sections                       sections with student / period counts
  POST /sections                       create a section (CSE-A, CSE-B ...)
  POST /sections/<id>/delete           delete an EMPTY section
  POST /sections/<id>/students         put many students into a section at once (list of roll numbers)
  GET  /attendance?date=YYYY-MM-DD     per section + subject: total / present / absent for that day
  GET  /attendance/session/<id>        every student of that class with present / absent
  POST /students/<student_id>/section  put a student in a section
  GET  /timetable                      all periods (+ faculty and section lists for the form)
  POST /timetable                      add a period  -> ALSO gives that faculty access to the subject+section
  POST /timetable/<id>/delete          remove a period
  GET  /reports/attendance.csv         every attendance record
  GET  /reports/low-attendance         students under the attendance threshold
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    AttendanceRecord, AttendanceSession, AuditLog, Classroom, Department, FacultySubjectMapping,
    Section, SignupRequest, Student, Subject, Timetable, User,
)
from routes.api_live import _csv_safe
from services.live_session_service import PERIOD_MINUTES, close_stale_sessions, record_summary, takes_subject

api_admin_bp = Blueprint("api_admin", __name__, url_prefix="/api/admin")

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
THRESHOLD = 75
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,49}$")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*a, **kw):
        if current_user.role != "admin":
            return jsonify({"ok": False, "message": "Admin access only."}), 403
        return view(*a, **kw)
    return wrapper


def _err(msg, status=400):
    return jsonify({"ok": False, "message": msg}), status


def _academic_year() -> str:
    t = date.today()
    return f"{t.year}-{(t.year + 1) % 100:02d}" if t.month >= 6 else f"{t.year - 1}-{t.year % 100:02d}"


def _hhmm(t) -> str:
    return t.strftime("%H:%M")


def _find_or_create_section(name: str) -> Section:
    """'CSE-A' -> department CSE + section CSE-A (reuses existing rows)."""
    code = name.split("-")[0].strip().upper()[:20] or name.upper()[:20]
    dept = Department.query.filter(func.upper(Department.code) == code).first()
    if dept is None:
        dept = Department(code=code, name=code)
        if Department.query.filter(func.lower(Department.name) == code.lower()).first():
            dept.name = f"{code} Department"
        db.session.add(dept)
        db.session.flush()
    section = (Section.query.filter(func.lower(Section.name) == name.lower(), Section.department_id == dept.id)
               .order_by(Section.academic_year.desc(), Section.semester.desc()).first())
    if section is None:
        section = Section(name=name, department_id=dept.id, year=1, semester=1, academic_year=_academic_year())
        db.session.add(section)
        db.session.flush()
    return section


def _find_or_create_subject(name: str, section: Section) -> Subject:
    subject = Subject.query.filter(func.lower(Subject.name) == name.lower(),
                                   Subject.department_id == section.department_id).first()
    if subject is not None:
        return subject
    dept = db.session.get(Department, section.department_id)
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name)).upper()[:8] or "SUB"
    base, code, n = f"{dept.code}-{initials}"[:26], None, 1
    code = base
    while Subject.query.filter_by(code=code).first():
        n += 1
        code = f"{base}{n}"
    subject = Subject(name=name, code=code, department_id=section.department_id, semester=section.semester)
    db.session.add(subject)
    db.session.flush()
    return subject


# ---------------------------------------------------------------- overview / users
@api_admin_bp.get("/overview")
@admin_required
def overview():
    return jsonify({
        "ok": True,
        "users": User.query.count(),
        "faculty": User.query.filter(User.role.in_(("faculty", "hod"))).count(),
        "periods": Timetable.query.filter_by(is_active=True).count(),
        "records": AttendanceRecord.query.count(),
        "students": Student.query.count(),
        "sections": Section.query.count(),
        "pending": SignupRequest.query.count(),
    })


@api_admin_bp.get("/users")
@admin_required
def users():
    rows = (db.session.query(User, Student, Section).outerjoin(Student, Student.user_id == User.id)
            .outerjoin(Section, Student.section_id == Section.id).order_by(User.role, User.id).all())
    pending = {r.user_id: r.requested_role for r in SignupRequest.query.all()}
    return jsonify({
        "ok": True,
        "users": [{
            "id": u.id, "student_id": st.id if st else None, "name": u.name, "role": u.role,
            "identifier": st.roll_number if st else str(u.id), "email": u.email,
            "section": sec.name if sec else None, "active": bool(u.is_active),
            "pending": u.id in pending, "requested_role": pending.get(u.id),
        } for u, st, sec in rows],
        "sections": [s.name for s in Section.query.order_by(Section.name).all()],
    })


@api_admin_bp.post("/users")
@admin_required
def create_user():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip().lower()
    password = d.get("password") or ""
    role = (d.get("role") or "faculty").strip().lower()
    roll = re.sub(r"\s+", "", str(d.get("roll_number") or "")).upper()
    section_name = (d.get("section") or "").strip()
    if role not in ("faculty", "admin", "student"):
        return _err("Role must be faculty, admin or student.")
    if not 2 <= len(name) <= 100:
        return _err("Enter the person's full name (2-100 characters).")
    if not EMAIL_RE.match(email) or len(email) > 120:
        return _err("Enter a valid e-mail address.")
    if not 8 <= len(password) <= 128:
        return _err("Password must be 8-128 characters.")
    if role == "student":
        if not re.match(r"^[A-Z0-9_.-]{2,50}$", roll):
            return _err("Enter the student's roll number (letters, digits, - _ . only).")
        if Student.query.filter(func.upper(Student.roll_number) == roll).first():
            return _err("A student with this roll number already exists.", 409)
        if section_name and not SECTION_RE.match(section_name):
            return _err("Invalid section name.")
    if User.query.filter(func.lower(User.email) == email).first():
        return _err("A user with this e-mail already exists.", 409)
    try:
        u = User(email=email, name=name, role=role, is_active=True)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()
        if role == "student":
            st = Student(user_id=u.id, roll_number=roll, year=1)
            if section_name:
                sec = _find_or_create_section(section_name)
                st.section_id, st.department_id, st.year = sec.id, sec.department_id, (sec.year or 1)
            db.session.add(st)
        db.session.add(AuditLog(user_id=current_user.id, action="create_user", entity_type="User",
                                entity_id=u.id, new_value=f"role={role}, email={email}"))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("A user with this e-mail or roll number already exists.", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("create_user failed")
        return _err("Could not create the account.", 500)
    who = f"Sign in with roll number {roll}" if role == "student" else f"Sign-in ID: {u.id}"
    return jsonify({"ok": True, "id": u.id, "message": f"{role.title()} account created. {who}"}), 201


@api_admin_bp.post("/users/<int:user_id>/active")
@admin_required
def set_active(user_id: int):
    u = db.session.get(User, user_id)
    if u is None:
        return _err("User not found.", 404)
    if u.id == current_user.id:
        return _err("You cannot disable your own account.")
    if SignupRequest.query.filter_by(user_id=u.id).first():
        return _err("This account is waiting for approval. Use Approve or Reject.")
    u.is_active = bool((request.get_json(silent=True) or {}).get("active"))
    db.session.commit()
    return jsonify({"ok": True, "active": u.is_active})


@api_admin_bp.post("/users/<int:user_id>/approve")
@admin_required
def approve_user(user_id: int):
    req = SignupRequest.query.filter_by(user_id=user_id).first()
    u = db.session.get(User, user_id)
    if req is None or u is None:
        return _err("There is no pending request for this user.", 404)
    u.is_active = True
    db.session.delete(req)
    db.session.add(AuditLog(user_id=current_user.id, action="approve_signup", entity_type="User",
                            entity_id=u.id, new_value=f"role={u.role}"))
    db.session.commit()
    return jsonify({"ok": True, "message": f"{u.name} approved. Sign-in ID: {u.id}"})


@api_admin_bp.post("/users/<int:user_id>/reject")
@admin_required
def reject_user(user_id: int):
    req = SignupRequest.query.filter_by(user_id=user_id).first()
    u = db.session.get(User, user_id)
    if req is None or u is None:
        return _err("There is no pending request for this user.", 404)
    name = u.name
    try:
        db.session.delete(req)
        db.session.flush()
        db.session.delete(u)
        db.session.commit()
    except Exception:                       # could not delete (linked rows): keep the account disabled instead
        db.session.rollback()
        req = SignupRequest.query.filter_by(user_id=user_id).first()
        if req:
            db.session.delete(req)
        u = db.session.get(User, user_id)
        if u:
            u.is_active = False
        db.session.commit()
    return jsonify({"ok": True, "message": f"Request from {name} rejected."})


@api_admin_bp.post("/users/<int:user_id>/email")
@admin_required
def set_email(user_id: int):
    u = db.session.get(User, user_id)
    if u is None:
        return _err("User not found.", 404)
    email = ((request.get_json(silent=True) or {}).get("email") or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 120:
        return _err("Enter a valid e-mail address.")
    other = User.query.filter(func.lower(User.email) == email, User.id != u.id).first()
    if other:
        return _err("Another account already uses this e-mail.", 409)
    u.email = email
    db.session.commit()
    return jsonify({"ok": True, "email": email})


@api_admin_bp.post("/students/<int:student_id>/section")
@admin_required
def set_section(student_id: int):
    st = db.session.get(Student, student_id)
    if st is None:
        return _err("Student not found.", 404)
    name = ((request.get_json(silent=True) or {}).get("section") or "").strip()
    if not name:
        st.section_id = None
    else:
        if not SECTION_RE.match(name):
            return _err("Invalid section name.")
        sec = _find_or_create_section(name)
        st.section_id, st.department_id = sec.id, sec.department_id
    db.session.commit()
    return jsonify({"ok": True, "section": name or None})


# ---------------------------------------------------------------- timetable
def _period_rows():
    rows = (db.session.query(Timetable, FacultySubjectMapping, Subject, Section, User, Classroom)
            .join(FacultySubjectMapping, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
            .join(Subject, FacultySubjectMapping.subject_id == Subject.id)
            .join(Section, FacultySubjectMapping.section_id == Section.id)
            .join(User, FacultySubjectMapping.faculty_id == User.id)
            .outerjoin(Classroom, Timetable.classroom_id == Classroom.id)
            .filter(Timetable.is_active.is_(True))
            .order_by(Timetable.day_of_week, Timetable.start_time).all())
    return [{
        "id": t.id, "day": DAYS[t.day_of_week % 7], "no": t.period_number, "start": _hhmm(t.start_time),
        "end": _hhmm(t.end_time), "section": sec.name, "subject": subj.name, "code": subj.code,
        "faculty": fac.name, "faculty_id": fac.id, "room": room.room_number if room else "",
    } for t, _m, subj, sec, fac, room in rows]


@api_admin_bp.get("/timetable")
@admin_required
def timetable():
    faculty = User.query.filter(User.role.in_(("faculty", "hod")), User.is_active.is_(True)).order_by(User.name).all()
    return jsonify({
        "ok": True, "periods": _period_rows(),
        "faculty": [{"id": f.id, "name": f.name} for f in faculty],
        "sections": [s.name for s in Section.query.order_by(Section.name).all()],
    })


@api_admin_bp.post("/timetable")
@admin_required
def add_period():
    d = request.get_json(silent=True) or {}
    day = d.get("day")
    section_name = (d.get("section") or "").strip()
    subject_name = (d.get("subject") or "").strip()
    room_no = (d.get("room") or "").strip()
    try:
        faculty_id = int(d.get("faculty_id"))
        period_no = int(d.get("no"))
        start = datetime.strptime(str(d.get("start")), "%H:%M").time()
        end = datetime.strptime(str(d.get("end")), "%H:%M").time()
    except (TypeError, ValueError):
        return _err("Fill in period number, start/end time and faculty.")
    if day not in DAYS or period_no < 1:
        return _err("Choose a valid day and period number.")
    if not SECTION_RE.match(section_name):
        return _err("Enter a section such as CSE-A.")
    if not 2 <= len(subject_name) <= 100 or not 1 <= len(room_no) <= 30:
        return _err("Enter the subject and the classroom.")
    start_dt = datetime.combine(date.today(), start)
    end = (start_dt + timedelta(minutes=PERIOD_MINUTES)).time()      # every period is 45 minutes
    if end <= start:
        return _err("A period must start before 23:15 so that it ends on the same day.")
    fac = db.session.get(User, faculty_id)
    if fac is None or fac.role not in ("faculty", "hod") or not fac.is_active:
        return _err("Pick an active faculty member.")
    di = DAYS.index(day)

    try:
        section = _find_or_create_section(section_name)
        subject = _find_or_create_subject(subject_name, section)
        mapping = FacultySubjectMapping.query.filter_by(
            faculty_id=fac.id, subject_id=subject.id, section_id=section.id,
            academic_year=section.academic_year, semester=section.semester).first()
        if mapping is None:
            mapping = FacultySubjectMapping(faculty_id=fac.id, subject_id=subject.id, section_id=section.id,
                                            academic_year=section.academic_year, semester=section.semester)
            db.session.add(mapping)
            db.session.flush()

        same = (db.session.query(Timetable).join(FacultySubjectMapping,
                Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
                .filter(FacultySubjectMapping.section_id == section.id, Timetable.day_of_week == di,
                        Timetable.period_number == period_no, Timetable.is_active.is_(True)).first())
        if same:
            db.session.rollback()
            return _err(f"{section.name} already has period {period_no} on {day}.", 409)
        clash = (db.session.query(Timetable).join(FacultySubjectMapping,
                 Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
                 .filter(FacultySubjectMapping.faculty_id == fac.id, Timetable.day_of_week == di,
                         Timetable.is_active.is_(True), Timetable.start_time < end, start < Timetable.end_time).first())
        if clash:
            db.session.rollback()
            return _err(f"{fac.name} is already teaching at that time.", 409)

        room = Classroom.query.filter(func.lower(Classroom.room_number) == room_no.lower()).first()
        if room is None:
            room = Classroom(room_number=room_no, department_id=section.department_id)
            db.session.add(room)
            db.session.flush()
        t = Timetable(faculty_subject_mapping_id=mapping.id, classroom_id=room.id, day_of_week=di,
                      period_number=period_no, start_time=start, end_time=end, is_active=True)
        db.session.add(t)
        db.session.add(AuditLog(user_id=current_user.id, action="add_period", entity_type="Timetable",
                                entity_id=0, new_value=f"{day} P{period_no} {subject.code} {section.name} faculty={fac.id}"))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("That period conflicts with an existing record.", 409)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("add_period failed")
        return _err("Could not add the period.", 500)
    return jsonify({"ok": True, "message": f"Added. {fac.name} can now mark attendance for {subject.name} · {section.name}."}), 201


@api_admin_bp.post("/timetable/<int:period_id>/delete")
@admin_required
def delete_period(period_id: int):
    t = db.session.get(Timetable, period_id)
    if t is None:
        return _err("Period not found.", 404)
    mapping_id = t.faculty_subject_mapping_id
    db.session.delete(t)
    db.session.flush()
    if not Timetable.query.filter_by(faculty_subject_mapping_id=mapping_id).first():
        m = db.session.get(FacultySubjectMapping, mapping_id)   # no periods left -> faculty loses that class
        if m is not None:
            db.session.delete(m)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- sections
@api_admin_bp.get("/sections")
@admin_required
def sections():
    students = dict(db.session.query(Student.section_id, func.count(Student.id)).group_by(Student.section_id).all())
    periods = dict(db.session.query(FacultySubjectMapping.section_id, func.count(Timetable.id))
                   .join(Timetable, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
                   .filter(Timetable.is_active.is_(True)).group_by(FacultySubjectMapping.section_id).all())
    rows = db.session.query(Section, Department).join(Department, Section.department_id == Department.id)\
        .order_by(Section.name).all()
    return jsonify({"ok": True, "sections": [
        {"id": sec.id, "name": sec.name, "department": dept.code, "students": int(students.get(sec.id, 0)),
         "periods": int(periods.get(sec.id, 0))} for sec, dept in rows],
        "unassigned": int(students.get(None, 0))})


@api_admin_bp.post("/sections")
@admin_required
def create_section():
    name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
    if not SECTION_RE.match(name):
        return _err("Enter a section name such as CSE-A.")
    try:
        sec = _find_or_create_section(name)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _err("Could not create that section.", 409)
    return jsonify({"ok": True, "id": sec.id, "message": f"Section {sec.name} is ready."}), 201


@api_admin_bp.post("/sections/<int:section_id>/delete")
@admin_required
def delete_section(section_id: int):
    sec = db.session.get(Section, section_id)
    if sec is None:
        return _err("Section not found.", 404)
    if (Student.query.filter_by(section_id=sec.id).first()
            or FacultySubjectMapping.query.filter_by(section_id=sec.id).first()
            or AttendanceSession.query.filter_by(section_id=sec.id).first()):
        return _err("This section still has students, classes or attendance records, so it cannot be deleted.", 409)
    db.session.delete(sec)
    db.session.commit()
    return jsonify({"ok": True})


@api_admin_bp.post("/sections/<int:section_id>/students")
@admin_required
def add_students_to_section(section_id: int):
    sec = db.session.get(Section, section_id)
    if sec is None:
        return _err("Section not found.", 404)
    raw = (request.get_json(silent=True) or {}).get("rolls") or ""
    rolls = [r for r in re.split(r"[,\s;]+", str(raw)) if r][:500]
    if not rolls:
        return _err("Enter at least one roll number.")
    assigned, missing = 0, []
    for roll in rolls:
        st = Student.query.filter(func.upper(Student.roll_number) == roll.upper()).first()
        if st is None:
            missing.append(roll)
            continue
        st.section_id, st.department_id = sec.id, sec.department_id
        assigned += 1
    db.session.commit()
    return jsonify({"ok": True, "assigned": assigned, "not_found": missing,
                    "message": f"{assigned} student(s) added to {sec.name}." + (f" Not found: {', '.join(missing)}." if missing else "")})


# ---------------------------------------------------------------- attendance overview
def _parse_day():
    raw = (request.args.get("date") or "").strip()
    if not raw:
        return date.today()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


@api_admin_bp.get("/attendance")
@admin_required
def attendance_overview():
    day = _parse_day()
    if day is None:
        return _err("Use the date format YYYY-MM-DD.")
    try:
        close_stale_sessions()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("close_stale_sessions failed")
    totals = dict(db.session.query(Student.section_id, func.count(Student.id)).group_by(Student.section_id).all())
    rows = (db.session.query(AttendanceSession, Subject, Section, User)
            .join(Subject, AttendanceSession.subject_id == Subject.id)
            .join(Section, AttendanceSession.section_id == Section.id)
            .join(User, AttendanceSession.faculty_id == User.id)
            .filter(AttendanceSession.date == day)
            .order_by(Section.name, AttendanceSession.period_number, AttendanceSession.id).all())
    ids = [sess.id for sess, *_ in rows]
    present = {}
    if ids:
        present = dict(db.session.query(AttendanceRecord.session_id, func.count(AttendanceRecord.id))
                       .filter(AttendanceRecord.session_id.in_(ids), AttendanceRecord.status.in_(("present", "late")))
                       .group_by(AttendanceRecord.session_id).all())
    out = []
    for sess, subj, sec, fac in rows:
        total = int(totals.get(sec.id, 0))
        p = int(present.get(sess.id, 0))
        out.append({
            "session_id": sess.id, "section": sec.name, "subject": subj.name, "code": subj.code,
            "faculty": fac.name, "period": sess.period_number, "status": sess.status,
            "total": total, "present": p, "absent": max(0, total - p),
            "finished": sess.status == "completed",
        })
    return jsonify({"ok": True, "date": day.isoformat(), "sessions": out})


@api_admin_bp.get("/attendance/session/<int:session_id>")
@admin_required
def attendance_session_detail(session_id: int):
    sess = db.session.get(AttendanceSession, session_id)
    if sess is None:
        return _err("Session not found.", 404)
    students = (db.session.query(Student, User).join(User, Student.user_id == User.id)
                .filter(Student.section_id == sess.section_id).order_by(Student.roll_number).all())
    recs = {r.student_id: r for r in AttendanceRecord.query.filter_by(session_id=sess.id).all()}
    info = record_summary([r.id for r in recs.values()], sess)
    subj = db.session.get(Subject, sess.subject_id)
    out = []
    for st, u in students:
        r = recs.get(st.id)
        if r is None and not takes_subject(st.id, sess.subject_id):
            continue
        i = info.get(r.id) if r else None
        if r is None:
            status = "absent"
        else:
            status = "present" if r.status in ("present", "late") else "absent"
        out.append({"roll": st.roll_number, "name": u.name, "subject": subj.name if subj else "", "status": status,
                    "entry": i["entry"].isoformat() if i and i["entry"] else None,
                    "exit": i["exit"].isoformat() if i and i["exit"] else None})
    return jsonify({"ok": True, "students": out, "status": sess.status})


# ---------------------------------------------------------------- reports
@api_admin_bp.get("/reports/attendance.csv")
@admin_required
def attendance_csv():
    rows = (db.session.query(AttendanceRecord, AttendanceSession, Subject, Section, Student, User)
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .join(Subject, AttendanceSession.subject_id == Subject.id)
            .join(Section, AttendanceSession.section_id == Section.id)
            .join(Student, AttendanceRecord.student_id == Student.id)
            .join(User, Student.user_id == User.id)
            .order_by(AttendanceSession.date.desc(), AttendanceSession.id.desc(), Student.roll_number)
            .limit(50000).all())
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Date", "Period", "Subject", "Section", "Roll", "Name", "Status"])
    for rec, sess, subj, sec, st, u in rows:
        w.writerow([_csv_safe(v) for v in (sess.date, sess.period_number, subj.name, sec.name, st.roll_number,
                                           u.name, rec.status)])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=attendance_report.csv"})


@api_admin_bp.get("/reports/low-attendance")
@admin_required
def low_attendance():
    present = func.sum(case((AttendanceRecord.status.in_(("present", "late")), 1), else_=0))
    rows = (db.session.query(Student, User, Section, func.count(AttendanceRecord.id), present)
            .join(AttendanceRecord, AttendanceRecord.student_id == Student.id)
            .join(User, Student.user_id == User.id).outerjoin(Section, Student.section_id == Section.id)
            .group_by(Student.id, User.id, Section.id).all())
    out = []
    for st, u, sec, total, pres in rows:
        pres = int(pres or 0)
        pct = round(pres * 100 / total, 1) if total else 0
        if pct < THRESHOLD:
            out.append({"roll": st.roll_number, "name": u.name, "section": sec.name if sec else "-",
                        "present": pres, "total": int(total), "pct": pct})
    out.sort(key=lambda r: r["pct"])
    return jsonify({"ok": True, "threshold": THRESHOLD, "students": out})
