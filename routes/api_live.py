"""Live Attendance API (faculty).  Prefix: /api/live

  GET  /options                    subjects + sections this faculty may take attendance for
  POST /sessions                   start (or resume today's) session   {subject_id, section_id}
  POST /sessions/<id>/frame        send ONE jpeg frame (multipart field "frame") -> recognised faces
  GET  /sessions/<id>/records      attendance records + summary for the session
  GET  /sessions/<id>/export.csv   the same records as CSV
  POST /sessions/<id>/end          close session; unseen students become absent

POSTs need the X-CSRFToken header (see frontend_integration/api.ts).
A student is marked present only when (1) the face matches above the threshold,
(2) the matched roll number exists in the students table, and (3) that student
belongs to the session's section.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from datetime import datetime as _dt
from functools import wraps

from flask import Blueprint, Response, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from services.live_session_service import (
    MIN_PRESENT_MINUTES, PERIOD_MINUTES, aware as _aw, apply_rule, close_stale_sessions, finalize_session,
    last_segment, open_segment, record_summary, register_entry, register_exit, takes_subject,
)
from models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    FaceRecognitionLog,
    FacultySubjectMapping,
    ObservationInterval,
    Section,
    Timetable,
    Student,
    Subject,
    User,
)

api_live_bp = Blueprint("api_live", __name__, url_prefix="/api/live")

JUST_EXITED_SECONDS = 90   # a student who just pressed Exit and is still at the camera is not an error
MAX_FRAME_BYTES = 2 * 1024 * 1024


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def faculty_api_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role not in ("faculty", "hod"):
            return jsonify({"ok": False, "message": "Faculty access only."}), 403
        return view(*args, **kwargs)
    return wrapper


def _err(message: str, status: int):
    return jsonify({"ok": False, "message": message}), status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt):
    if dt is not None and dt.tzinfo is None:  # MySQL returns naive datetimes
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt):
    dt = _aware(dt)
    return dt.isoformat() if dt else None


def _recognizer():
    rec = current_app.extensions.get("attendai_recognizer")
    if rec is None:
        from services.live_recognizer import LiveRecognizer  # imports OpenCV lazily
        rec = LiveRecognizer(current_app)
        current_app.extensions["attendai_recognizer"] = rec
    return rec


def _own_session(session_id: int):
    s = db.session.get(AttendanceSession, session_id)
    if s is None:
        return None, _err("Session not found.", 404)
    if s.faculty_id != current_user.id:
        return None, _err("This is not your session.", 403)
    return s, None


def _student_by_label(label: str):
    """Dataset folder name == roll number (or admission number)."""
    u = label.upper()
    return Student.query.filter(
        (func.upper(Student.roll_number) == u) | (func.upper(Student.admission_number) == u)
    ).first()


def _section_students(section_id: int):
    return Student.query.filter_by(section_id=section_id).all()


def _present_count(session_id: int) -> int:
    return AttendanceRecord.query.filter(
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.status.in_(("present", "late")),
    ).count()


def _enrolled_in_section(section_id: int) -> int:
    labels = {l.upper() for l in _recognizer().enrolled_labels()}
    return sum(
        1
        for st in _section_students(section_id)
        if st.roll_number.upper() in labels
        or (st.admission_number and st.admission_number.upper() in labels)
    )


# --------------------------------------------------------------------------
# options
# --------------------------------------------------------------------------
@api_live_bp.get("/options")
@faculty_api_required
def options():
    try:
        close_stale_sessions()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("close_stale_sessions failed")
    rows = (
        db.session.query(FacultySubjectMapping, Subject, Section)
        .join(Subject, FacultySubjectMapping.subject_id == Subject.id)
        .join(Section, FacultySubjectMapping.section_id == Section.id)
        .filter(FacultySubjectMapping.faculty_id == current_user.id)
        .order_by(Subject.name, Section.name)
        .all()
    )
    subjects, sections = {}, {}
    for _m, subj, sec in rows:
        s = subjects.setdefault(
            subj.id, {"id": subj.id, "name": subj.name, "code": subj.code, "section_ids": []}
        )
        if sec.id not in s["section_ids"]:
            s["section_ids"].append(sec.id)
        sections[sec.id] = {"id": sec.id, "name": sec.name}

    ready, message = _recognizer().readiness()
    return jsonify(
        {
            "ok": True,
            "subjects": list(subjects.values()),
            "sections": list(sections.values()),
            "recognition_ready": ready,
            "recognition_message": message,
        }
    )


# --------------------------------------------------------------------------
# start / resume session
# --------------------------------------------------------------------------
@api_live_bp.post("/sessions")
@faculty_api_required
def start_session():
    data = request.get_json(silent=True) or {}
    try:
        subject_id = int(data.get("subject_id"))
        section_id = int(data.get("section_id"))
    except (TypeError, ValueError):
        return _err("Please select a subject and a section.", 400)

    mapped = FacultySubjectMapping.query.filter_by(
        faculty_id=current_user.id, subject_id=subject_id, section_id=section_id
    ).first()
    if not mapped:
        return _err("You are not assigned to this subject and section.", 403)

    ready, message = _recognizer().readiness()
    if not ready:
        return _err(message, 503)

    today = date.today()
    now_local = _dt.now()
    now_min = now_local.hour * 60 + now_local.minute
    entries = Timetable.query.filter_by(
        faculty_subject_mapping_id=mapped.id, day_of_week=today.weekday(), is_active=True
    ).all()
    if current_app.config.get("ENFORCE_TIMETABLE"):
        inside = any(
            t.start_time.hour * 60 + t.start_time.minute - 10 <= now_min <= t.end_time.hour * 60 + t.end_time.minute + 10
            for t in entries
        )
        if not inside:
            return _err("This class is not scheduled for the current time (see the timetable).", 403)
    # Today's session for this class (any status except cancelled): resume it, or re-open it if it was ended.
    session = (
        AttendanceSession.query.filter_by(
            faculty_id=current_user.id, subject_id=subject_id, section_id=section_id, date=today
        )
        .filter(AttendanceSession.status != "cancelled")
        .order_by(AttendanceSession.id.desc())
        .first()
    )
    created = False
    if session is None:
        # Link to today's timetable period for this faculty+subject+section (closest to now), if there is one.
        entry = min(
            entries,
            key=lambda t: abs((t.start_time.hour * 60 + t.start_time.minute) - (now_local.hour * 60 + now_local.minute)),
            default=None,
        )
        last_period = (
            db.session.query(func.max(AttendanceSession.period_number))
            .filter_by(section_id=section_id, date=today)
            .scalar()
        )
        duration = PERIOD_MINUTES          # every period is 45 minutes
        session = AttendanceSession(
            timetable_id=entry.id if entry else None,
            classroom_id=entry.classroom_id if entry else None,
            faculty_id=current_user.id,
            subject_id=subject_id,
            section_id=section_id,
            date=today,
            period_number=entry.period_number if entry else (last_period or 0) + 1,
            start_time=_now(),
            scheduled_duration_minutes=duration,
            status="in_progress",
        )
        db.session.add(session)
        created = True
    elif session.status == "completed":
        session.completed_at = None      # re-opened: students marked absent at "End class" can still be recognised
        session.end_time = None
    session.camera_active = True
    session.status = "in_progress"
    db.session.commit()

    return jsonify(
        {
            "ok": True,
            "created": created,
            "session": {
                "id": session.id,
                "date": session.date.isoformat(),
                "period": session.period_number,
                "status": session.status,
            },
            "present_count": _present_count(session.id),
            "enrolled_count": _enrolled_in_section(section_id),
        }
    )


# --------------------------------------------------------------------------
# one frame in -> faces out (and attendance marked)
# --------------------------------------------------------------------------
@api_live_bp.post("/sessions/<int:session_id>/frame")
@faculty_api_required
def frame(session_id: int):
    session, error = _own_session(session_id)
    if error:
        return error
    if session.status in ("completed", "cancelled"):
        return _err("This session has ended.", 409)

    mode = (request.form.get("mode") or "entry").strip().lower()
    if mode not in ("entry", "exit"):
        return _err("Choose Entry or Exit.", 400)
    upload = request.files.get("frame")
    if upload is None:
        return _err("No frame received.", 400)
    data = upload.read(MAX_FRAME_BYTES + 1)
    if not data or len(data) > MAX_FRAME_BYTES:
        return _err("Frame is empty or larger than 2 MB.", 400)

    try:
        hits, latency_ms = _recognizer().analyse(data)
    except ValueError as exc:
        return _err(str(exc), 400)
    except RuntimeError as exc:
        return _err(str(exc), 503)

    now = _now()
    faces, newly_marked = [], 0
    cache = {}
    try:
        for hit in hits:
            face = {
                "box": {"x": hit.x, "y": hit.y, "w": hit.w, "h": hit.h},
                "score": round(hit.score, 3),
                "state": "unknown",
                "roll_number": None,
                "name": None,
            }
            if hit.label:
                if hit.label not in cache:
                    cache[hit.label] = _student_by_label(hit.label)
                student = cache[hit.label]
                if student is None:
                    face["state"] = "unregistered"       # in face DB but no student row
                elif student.section_id is None:
                    face["state"] = "no_section"         # signed up + enrolled, but no section assigned yet
                    face["roll_number"] = student.roll_number
                    face["name"] = student.user.name if student.user else student.roll_number
                elif student.section_id != session.section_id:
                    face["state"] = "not_in_section"     # real student, wrong class -> NOT marked
                    face["roll_number"] = student.roll_number
                elif not takes_subject(student.id, session.subject_id):
                    face["state"] = "not_in_subject"     # in the section but does not take THIS subject -> NOT marked
                    face["roll_number"] = student.roll_number
                    face["name"] = student.user.name if student.user else student.roll_number
                else:
                    face["roll_number"] = student.roll_number
                    face["name"] = student.user.name if student.user else student.roll_number
                    state = _apply_mode(session, student, hit.score, now, mode)
                    newly_marked += int(state in ("entered", "exited"))
                    face["state"] = state
            faces.append(face)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Live attendance frame failed")
        return _err("Could not save attendance for this frame.", 500)

    return jsonify(
        {
            "ok": True,
            "faces": faces,
            "faces_in_frame": len(faces),
            "latency_ms": latency_ms,
            "newly_marked": newly_marked,
            "mode": mode,
            "present_count": _present_count(session.id),
            "inside_count": _inside_count(session.id),
            "outside_schedule": _outside_schedule(session),
        }
    )


def _outside_schedule(session) -> bool:
    """True when this session is linked to a timetable period and the clock is >10 min outside it."""
    if not session.timetable_id or session.date != date.today():
        return False
    t = db.session.get(Timetable, session.timetable_id)
    if t is None:
        return False
    n = _dt.now()
    now_min = n.hour * 60 + n.minute
    return not (t.start_time.hour * 60 + t.start_time.minute - 10 <= now_min <= t.end_time.hour * 60 + t.end_time.minute + 10)


def _inside_count(session_id: int) -> int:
    return (db.session.query(ObservationInterval.id)
            .join(AttendanceRecord, ObservationInterval.record_id == AttendanceRecord.id)
            .filter(AttendanceRecord.session_id == session_id, ObservationInterval.end_time.is_(None)).count())


def _apply_mode(session, student, score: float, now, mode: str) -> str:
    """Entry / Exit for one recognised student. Returns the state shown on the camera:
         entered | already_inside | exited | just_exited | not_inside
    Exit is only possible after an Entry; a new Entry is only possible after an Exit."""
    record = AttendanceRecord.query.filter_by(session_id=session.id, student_id=student.id).first()
    seg = open_segment(record.id) if record is not None else None

    if mode == "entry":
        if seg is not None:
            return "already_inside"                 # must press Exit before entering again
        if record is None:
            record = AttendanceRecord(
                session_id=session.id, student_id=student.id, status="present", first_seen_at=now,
                last_seen_at=now, confidence_score=float(score), total_observed_seconds=0.0, coverage_percentage=0.0)
            db.session.add(record)
            db.session.flush()
        else:
            record.confidence_score = max(float(score), record.confidence_score or 0.0)
        register_entry(record, now)
        if not record.is_manually_modified:
            record.status = "present"               # present from the moment of entry, with that time
        db.session.add(FaceRecognitionLog(session_id=session.id, student_id=student.id, confidence_score=float(score),
                                          capture_time=now, recognition_status="entry", frame_number=0))
        return "entered"

    # exit
    if record is None or seg is None:
        last = last_segment(record.id) if record is not None else None
        if last is not None and last.end_time is not None and (now - _aw(last.end_time)).total_seconds() <= JUST_EXITED_SECONDS:
            return "just_exited"
        return "not_inside"                         # Exit is not available before an Entry
    register_exit(record, session, now)
    db.session.add(FaceRecognitionLog(session_id=session.id, student_id=student.id, confidence_score=float(score),
                                      capture_time=now, recognition_status="exit", frame_number=0))
    return "exited"


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------
def _records_payload(session):
    rows = (
        db.session.query(AttendanceRecord, Student, User)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .join(User, Student.user_id == User.id)
        .filter(AttendanceRecord.session_id == session.id)
        .order_by(AttendanceRecord.first_seen_at.is_(None), AttendanceRecord.first_seen_at, Student.roll_number)
        .all()
    )
    info = record_summary([rec.id for rec, _st, _u in rows], session)
    subject = db.session.get(Subject, session.subject_id)
    sub_name = subject.name if subject else ""
    records = []
    for rec, st, user in rows:
        s = info.get(rec.id)
        records.append(
            {
                "roll_number": st.roll_number,
                "name": user.name,
                "subject": sub_name,
                "entry": _iso(s["entry"]) if s else None,
                "exit": _iso(s["exit"]) if s else None,
                "inside": bool(s and s["inside"]),
                "status": rec.status,
            }
        )
    present = sum(1 for r in records if r["status"] in ("present", "late"))
    absent_marked = sum(1 for r in records if r["status"] == "absent")
    expected = sum(1 for st in _section_students(session.section_id) if takes_subject(st.id, session.subject_id))
    done = session.status == "completed"
    summary = {
        "present": present,
        "absent": absent_marked if done else max(0, expected - present),
        "total": expected,
        "inside": sum(1 for r in records if r["inside"]),
        "period_minutes": PERIOD_MINUTES,
        "min_minutes": MIN_PRESENT_MINUTES,
    }
    return records, summary


@api_live_bp.get("/sessions/<int:session_id>/records")
@faculty_api_required
def records(session_id: int):
    session, error = _own_session(session_id)
    if error:
        return error
    recs, summary = _records_payload(session)
    return jsonify({"ok": True, "session_status": session.status, "summary": summary, "records": recs})


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # block formula injection


@api_live_bp.get("/sessions/<int:session_id>/export.csv")
@faculty_api_required
def export_csv(session_id: int):
    session, error = _own_session(session_id)
    if error:
        return error
    recs, _ = _records_payload(session)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Roll", "Name", "Subject", "Entry", "Exit", "Status"])
    for r in recs:
        w.writerow([_csv_safe(r[k]) for k in ("roll_number", "name", "subject", "entry", "exit", "status")])
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=attendance_session_{session.id}.csv"},
    )


# --------------------------------------------------------------------------
# end session
# --------------------------------------------------------------------------
@api_live_bp.post("/sessions/<int:session_id>/end")
@faculty_api_required
def end_session(session_id: int):
    session, error = _own_session(session_id)
    if error:
        return error
    if session.status == "completed":
        return jsonify({"ok": True, "message": "Session already ended.", "present": _present_count(session.id)})
    try:
        present, absent = finalize_session(session, closed_by_id=current_user.id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("End session failed")
        return _err("Could not end the session.", 500)
    return jsonify({"ok": True, "message": "Session ended.", "present": present, "absent": absent})


# --------------------------------------------------------------------------
# history: every class this faculty has taken, read from the database (survives reloads and restarts)
# --------------------------------------------------------------------------
def _session_counts(session):
    """(present, absent, total) for one session. Students not seen yet count as absent (they were not in class)."""
    students = [st for st in _section_students(session.section_id) if takes_subject(st.id, session.subject_id)]
    ids = {st.id for st in students}
    recs = {r.student_id: r for r in AttendanceRecord.query.filter_by(session_id=session.id).all()}
    present = sum(1 for sid in ids if sid in recs and recs[sid].status in ("present", "late"))
    for sid, r in recs.items():                      # present students that are no longer listed for the subject
        if sid not in ids and r.status in ("present", "late"):
            present += 1
    total = len(ids | {sid for sid, r in recs.items() if r.status in ("present", "late")})
    return present, max(0, total - present), total


@api_live_bp.get("/history")
@faculty_api_required
def history():
    try:
        close_stale_sessions()
    except Exception:
        db.session.rollback()
    raw = (request.args.get("date") or "").strip()
    q = (db.session.query(AttendanceSession, Subject, Section)
         .join(Subject, AttendanceSession.subject_id == Subject.id)
         .join(Section, AttendanceSession.section_id == Section.id)
         .filter(AttendanceSession.faculty_id == current_user.id, AttendanceSession.status != "cancelled"))
    if raw:
        try:
            q = q.filter(AttendanceSession.date == datetime.strptime(raw, "%Y-%m-%d").date())
        except ValueError:
            return _err("Use the date format YYYY-MM-DD.", 400)
    rows = q.order_by(AttendanceSession.date.desc(), AttendanceSession.period_number, AttendanceSession.id.desc()).limit(200).all()
    out = []
    for s, subj, sec in rows:
        p, a, t = _session_counts(s)
        out.append({"session_id": s.id, "date": s.date.isoformat(), "period": s.period_number, "subject": subj.name,
                    "code": subj.code, "section": sec.name, "present": p, "absent": a, "total": t,
                    "finished": s.status == "completed"})
    return jsonify({"ok": True, "sessions": out})


@api_live_bp.get("/history/session/<int:session_id>")
@faculty_api_required
def history_session(session_id: int):
    session, error = _own_session(session_id)
    if error:
        return error
    subj = db.session.get(Subject, session.subject_id)
    recs = {r.student_id: r for r in AttendanceRecord.query.filter_by(session_id=session.id).all()}
    info = record_summary([r.id for r in recs.values()], session)
    out = []
    for st in sorted(_section_students(session.section_id), key=lambda x: x.roll_number):
        if not takes_subject(st.id, session.subject_id) and st.id not in recs:
            continue
        r = recs.get(st.id)
        s = info.get(r.id) if r else None
        status = "absent" if r is None else ("present" if r.status in ("present", "late") else r.status)
        out.append({"roll": st.roll_number, "name": st.user.name if st.user else st.roll_number,
                    "subject": subj.name if subj else "", "status": status,
                    "entry": _iso(s["entry"]) if s else None, "exit": _iso(s["exit"]) if s else None,
                    "inside": bool(s and s["inside"])})
    return jsonify({"ok": True, "students": out, "finished": session.status == "completed"})
