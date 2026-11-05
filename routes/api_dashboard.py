"""Dashboards fed by the live attendance data.   Prefix: /api

  GET /api/dashboard           faculty: subjects, recent sessions, timetable, students-at-risk (own classes only)
  GET /api/student/dashboard   student: own attendance history per subject + own timetable

Both read the same AttendanceRecord rows that Live Attendance writes, so a student marked
present in class shows up in their dashboard on the next refresh.
"""

from __future__ import annotations

from flask import Blueprint, jsonify
from flask_login import current_user, login_required
from sqlalchemy import case, func

from extensions import db
from services.live_session_service import close_stale_sessions, record_summary, takes_subject
from models import (
    AttendanceRecord, AttendanceSession, Classroom, FacultySubjectMapping, Section, Student, Subject,
    Timetable, User, StudentSubject,
)

api_dashboard_bp = Blueprint("api_dashboard", __name__, url_prefix="/api")

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PRESENT = ("present", "late")
_present_expr = func.sum(case((AttendanceRecord.status.in_(PRESENT), 1), else_=0))


def _err(msg, status):
    return jsonify({"ok": False, "message": msg}), status


@api_dashboard_bp.get("/dashboard")
@login_required
def faculty_dashboard():
    if current_user.role not in ("faculty", "hod"):
        return _err("Faculty access only.", 403)
    uid = current_user.id
    try:
        close_stale_sessions()
    except Exception:
        db.session.rollback()

    mappings = (db.session.query(FacultySubjectMapping, Subject, Section)
                .join(Subject, FacultySubjectMapping.subject_id == Subject.id)
                .join(Section, FacultySubjectMapping.section_id == Section.id)
                .filter(FacultySubjectMapping.faculty_id == uid).all())

    # per-subject totals over this faculty's own sessions
    per_subject = {
        sid: (int(p or 0), int(t or 0))
        for sid, p, t in db.session.query(AttendanceSession.subject_id, _present_expr, func.count(AttendanceRecord.id))
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(AttendanceSession.faculty_id == uid).group_by(AttendanceSession.subject_id).all()
    }
    seen, subjects = set(), []
    for _m, subj, _sec in mappings:
        if subj.id in seen:
            continue
        seen.add(subj.id)
        p, t = per_subject.get(subj.id, (0, 0))
        subjects.append({"code": subj.code, "name": subj.name, "present": p, "total": t})

    # latest classes with present / absent counts (every faculty sees the same numbers for their own classes)
    from routes.api_live import _session_counts
    sess_rows = (db.session.query(AttendanceSession, Subject, Section)
                 .join(Subject, AttendanceSession.subject_id == Subject.id)
                 .join(Section, AttendanceSession.section_id == Section.id)
                 .filter(AttendanceSession.faculty_id == uid, AttendanceSession.status != "cancelled")
                 .order_by(AttendanceSession.date.desc(), AttendanceSession.id.desc()).limit(15).all())
    recent = []
    for sess, subj, sec in sess_rows:
        p, a, t = _session_counts(sess)
        recent.append([f"{sess.date.strftime('%d %b %Y')} · P{sess.period_number} · {subj.name} · {sec.name}",
                       f"{p} present · {a} absent"])

    timetable = [[DAYS[t.day_of_week % 7], t.start_time.strftime("%H:%M"), f"{subj.code} · {subj.name}",
                  room.room_number if room else "-"]
                 for t, subj, room in db.session.query(Timetable, Subject, Classroom)
                 .join(FacultySubjectMapping, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
                 .join(Subject, FacultySubjectMapping.subject_id == Subject.id)
                 .outerjoin(Classroom, Timetable.classroom_id == Classroom.id)
                 .filter(FacultySubjectMapping.faculty_id == uid, Timetable.is_active.is_(True))
                 .order_by(Timetable.day_of_week, Timetable.start_time).all()]

    # students in this faculty's sections, ranked by their attendance in this faculty's classes
    student_rows = (db.session.query(Student, User, _present_expr, func.count(AttendanceRecord.id))
                    .join(User, Student.user_id == User.id)
                    .join(AttendanceRecord, AttendanceRecord.student_id == Student.id)
                    .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
                    .filter(AttendanceSession.faculty_id == uid)
                    .group_by(Student.id, User.id).all())
    students = sorted(
        ({"roll": st.roll_number, "name": u.name, "pct": round(int(p or 0) * 100 / t, 1)} for st, u, p, t in student_rows if t),
        key=lambda s: s["pct"])[:100]

    return jsonify({"subjects": subjects, "recent": recent, "timetable": timetable, "students": students})


@api_dashboard_bp.get("/student/dashboard")
@login_required
def student_dashboard():
    if current_user.role != "student":
        return _err("Student access only.", 403)
    st = Student.query.filter_by(user_id=current_user.id).first()
    if st is None:
        return _err("Student profile not found.", 404)
    try:
        close_stale_sessions()
    except Exception:
        db.session.rollback()

    # Every class that was started for this student's section (and subject) is listed. If the student was not
    # marked present in it, it shows as ABSENT - the student sees both the present and the absent list.
    mine = {sid for (sid,) in db.session.query(StudentSubject.subject_id).filter_by(student_id=st.id)}
    recs = {r.session_id: r for r in AttendanceRecord.query.filter_by(student_id=st.id).all()}
    q = (db.session.query(AttendanceSession, Subject)
         .join(Subject, AttendanceSession.subject_id == Subject.id)
         .filter(AttendanceSession.status != "cancelled"))
    cond = AttendanceSession.id.in_(list(recs) or [0])
    if st.section_id:
        cond = cond | (AttendanceSession.section_id == st.section_id)
    sessions = q.filter(cond).order_by(AttendanceSession.date.desc(), AttendanceSession.id.desc()).limit(300).all()
    info = record_summary([r.id for r in recs.values()])

    records = []
    for sess, subj in sessions:
        rec = recs.get(sess.id)
        if rec is None and mine and subj.id not in mine:
            continue                                  # a subject this student does not take
        s = info.get(rec.id) if rec else None
        records.append({
            "date": sess.date.isoformat(), "period": sess.period_number, "subject": subj.name, "code": subj.code,
            "status": "present" if rec is not None and rec.status in PRESENT else "absent",
            "entry": s["entry"].isoformat() if s and s["entry"] else None,
            "exit": s["exit"].isoformat() if s and s["exit"] else None,
        })
    present = sum(1 for r in records if r["status"] == "present")
    total = len(records)

    timetable = []
    if st.section_id:
        timetable = [[DAYS[t.day_of_week % 7], f"{t.start_time:%H:%M} – {t.end_time:%H:%M}",
                      f"{subj.code} · {subj.name}", room.room_number if room else "-"]
                     for t, subj, room in db.session.query(Timetable, Subject, Classroom)
                     .join(FacultySubjectMapping, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
                     .join(Subject, FacultySubjectMapping.subject_id == Subject.id)
                     .outerjoin(Classroom, Timetable.classroom_id == Classroom.id)
                     .filter(FacultySubjectMapping.section_id == st.section_id, Timetable.is_active.is_(True))
                     .order_by(Timetable.day_of_week, Timetable.start_time).all()
                     if not mine or subj.id in mine]
    section = db.session.get(Section, st.section_id) if st.section_id else None
    return jsonify({
        "ok": True, "name": current_user.name, "roll": st.roll_number,
        "section": section.name if section else None,
        "present": present, "absent": total - present, "total": total,
        "overall": round(present * 100 / total) if total else 0,
        "records": records, "timetable": timetable,
    })
