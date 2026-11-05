"""Face enrolment API (faculty / hod / admin).  Prefix: /api/enroll

  GET  /students?q=              students (with enrolled flag + photo count) and the sections you may assign
  POST /<student_id>/samples     ONE webcam frame (multipart "frame" + consent=true) -> validated, saved to dataset/<roll>/NNN.jpg
  POST /<student_id>/finish      re-embeds that student's photos into face_database.npz, optional name / section

Same data as collect_faces.py + build_database.py, but driven from the browser.
"""

from __future__ import annotations

from functools import wraps

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from extensions import db
from models import AuditLog, FaceEmbedding, FaceEnrollment, FacultySubjectMapping, Section, Student, User

api_enroll_bp = Blueprint("api_enroll", __name__, url_prefix="/api/enroll")

MIN_SAMPLES = 5
MAX_SAMPLES = 20
MAX_FRAME_BYTES = 4 * 1024 * 1024


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapper(*a, **kw):
        if current_user.role not in ("faculty", "hod", "admin"):
            return jsonify({"ok": False, "message": "Staff access only."}), 403
        return view(*a, **kw)
    return wrapper


def _err(msg, status):
    return jsonify({"ok": False, "message": msg}), status


def _recognizer():
    rec = current_app.extensions.get("attendai_recognizer")
    if rec is None:
        from services.live_recognizer import LiveRecognizer
        rec = LiveRecognizer(current_app)
        current_app.extensions["attendai_recognizer"] = rec
    return rec


def _my_sections():
    q = db.session.query(Section)
    if current_user.role != "admin":
        ids = [m.section_id for m in FacultySubjectMapping.query.filter_by(faculty_id=current_user.id).all()]
        q = q.filter(Section.id.in_(ids or [0]))
    return q.order_by(Section.name).all()


def _enrolled_ids():
    """Enrolled = the student has stored faces (a finished enrolment, or faces rebuilt from dataset/<roll>/)."""
    marked = {sid for (sid,) in db.session.query(FaceEnrollment.student_id).distinct()}
    stored = {sid for (sid, n) in db.session.query(FaceEmbedding.student_id, func.count(FaceEmbedding.id))
              .group_by(FaceEmbedding.student_id).all() if n >= MIN_SAMPLES}
    have_any = {sid for (sid,) in db.session.query(FaceEmbedding.student_id).distinct()}
    return (marked & have_any) | stored


@api_enroll_bp.get("/students")
@staff_required
def students():
    q = (request.args.get("q") or "").strip()[:60]
    query = db.session.query(Student, User, Section).join(User, Student.user_id == User.id).outerjoin(
        Section, Student.section_id == Section.id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Student.roll_number.ilike(like), User.name.ilike(like)))
    rows = query.order_by(Student.roll_number).limit(200).all()
    done = _enrolled_ids()
    counts = dict(db.session.query(FaceEmbedding.student_id, func.count(FaceEmbedding.id)).group_by(FaceEmbedding.student_id).all())
    return jsonify({
        "ok": True,
        "students": [
            {
                "id": st.id, "roll_number": st.roll_number, "name": u.name,
                "section": sec.name if sec else None, "section_id": st.section_id,
                "enrolled": st.id in done, "samples": int(counts.get(st.id, 0)),
            }
            for st, u, sec in rows
        ],
        "sections": [{"id": s.id, "name": s.name} for s in _my_sections()],
        "min_samples": MIN_SAMPLES,
        "can_replace": current_user.role == "admin",
    })


def _consent(req) -> bool:
    return str(req.form.get("consent", "")).lower() in ("1", "true", "yes", "on")


@api_enroll_bp.post("/<int:student_id>/samples")
@staff_required
def add_sample(student_id: int):
    student = db.session.get(Student, student_id)
    if student is None:
        return _err("Student not found.", 404)
    if not _consent(request):
        return _err("The student's consent is required before capturing photos.", 400)
    upload = request.files.get("frame")
    if upload is None:
        return _err("No frame received.", 400)
    data = upload.read(MAX_FRAME_BYTES + 1)
    if not data or len(data) > MAX_FRAME_BYTES:
        return _err("Frame is empty or too large.", 400)

    from services.live_recognizer import SampleRejected
    rec = _recognizer()
    enrolled = FaceEnrollment.query.filter_by(student_id=student.id).first() is not None
    if enrolled and rec.count_samples(student.id) == 0:      # enrolment marker without any stored face: start over
        FaceEnrollment.query.filter_by(student_id=student.id).delete()
        db.session.commit()
        enrolled = False
    if enrolled:
        if request.form.get("replace") == "1" and current_user.role == "admin":
            FaceEnrollment.query.filter_by(student_id=student.id).delete()
            rec.clear_student(student.id)               # admin re-enrol: start again from zero
        else:
            return _err("This student is already enrolled. A face is enrolled only once.", 409)
    elif request.form.get("fresh") == "1":
        rec.clear_student(student.id)                   # discard an unfinished earlier attempt
    if rec.count_samples(student.id) >= MAX_SAMPLES:
        return _err("This student already has the maximum number of photos. Press Finish.", 409)
    try:
        crop, feat = rec.validate_and_embed(data, student)
        total = rec.save_sample(student, crop, feat)
    except SampleRejected as exc:
        return jsonify({"ok": True, "accepted": False, "message": str(exc), "samples": rec.count_samples(student.id)})
    except RuntimeError as exc:
        return _err(str(exc), 503)
    except (ValueError, OSError) as exc:
        return _err(str(exc), 400)
    return jsonify({"ok": True, "accepted": True, "samples": total, "message": "Sample saved."})


@api_enroll_bp.post("/<int:student_id>/finish")
@staff_required
def finish(student_id: int):
    student = db.session.get(Student, student_id)
    if student is None:
        return _err("Student not found.", 404)
    body = request.get_json(silent=True) or {}
    rec = _recognizer()
    n = rec.count_samples(student.id)
    if n < MIN_SAMPLES:
        return _err(f"Capture at least {MIN_SAMPLES} good photos first.", 400)

    section = None
    if body.get("section_id") not in (None, ""):
        try:
            section = db.session.get(Section, int(body["section_id"]))
        except (TypeError, ValueError):
            section = None
        if section is None:
            return _err("Unknown section.", 400)
        if current_user.role != "admin" and not FacultySubjectMapping.query.filter_by(
                faculty_id=current_user.id, section_id=section.id).first():
            return _err("You are not assigned to that section.", 403)
    try:
        name = (body.get("name") or "").strip()
        if 2 <= len(name) <= 100 and student.user:
            student.user.name = name
        if section is not None:
            student.section_id = section.id
            student.department_id = section.department_id
        if FaceEnrollment.query.filter_by(student_id=student.id).first() is None:
            for i in range(n):
                db.session.add(FaceEnrollment(student_id=student.id, embedding_index=i, enrolled_by_id=current_user.id))
            db.session.add(AuditLog(user_id=current_user.id, action="face_enrolled", entity_type="Student",
                                    entity_id=student.id, new_value=f"roll={student.roll_number}, embeddings={n}"))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Saving enrolment record failed")
        return _err("Face data saved, but the student record could not be updated.", 500)
    rec.invalidate()
    try:
        rec.export_backup()
    except Exception:
        current_app.logger.warning("face_database.npz backup not written", exc_info=True)
    return jsonify({"ok": True, "embeddings": n, "enrolled": True,
                    "message": f"{student.user.name if student.user else student.roll_number} enrolled with {n} face samples."})
