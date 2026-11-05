"""Rules for live attendance sessions: Entry / Exit, 45-minute periods, the 20-minute rule.

How presence works
------------------
* Every period is PERIOD_MINUTES (45) long.
* The student presses ENTRY  -> a presence segment opens (an ObservationInterval with start_time = entry time)
  and the student is marked PRESENT with that time.
* The student presses EXIT   -> the open segment is closed (end_time = exit time). Exit is only possible while
  the student is inside, and a second Entry is only possible after an Exit.
* Leaving and coming back (re-entry / re-exit) simply creates more segments.
* Time in class = sum of the segments, never more than PERIOD_MINUTES.
* A student with less than MIN_PRESENT_MINUTES (20) in class is ABSENT, otherwise PRESENT.
* When the class ends, segments still open are closed at the end of the class (or of the 45-minute period),
  and every student of the section who never entered is marked ABSENT.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Tuple

from extensions import db
from models import (
    AttendanceRecord, AttendanceSession, AuditLog, ObservationInterval, Student, StudentSubject,
)

PERIOD_MINUTES = 45          # length of every period
MIN_PRESENT_MINUTES = 20     # less than this in class = absent
OPEN_STATUSES = ("started", "in_progress", "paused")


def aware(dt):
    if dt is not None and dt.tzinfo is None:   # MySQL returns naive datetimes
        return dt.replace(tzinfo=timezone.utc)
    return dt


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- pure rules (no database)
def status_for_minutes(minutes: float) -> str:
    """The 20-minute rule."""
    return "present" if minutes >= MIN_PRESENT_MINUTES else "absent"


def period_end(session) -> Optional[datetime]:
    start = aware(getattr(session, "start_time", None))
    return start + timedelta(minutes=PERIOD_MINUTES) if start else None


def total_seconds(segments: Iterable[Tuple[datetime, Optional[datetime]]], now: datetime,
                  cap_end: Optional[datetime] = None) -> float:
    """Sum of (exit - entry); an open segment runs until `now` (or cap_end). Never more than one period."""
    total = 0.0
    for start, end in segments:
        start = aware(start)
        stop = aware(end) if end is not None else now
        if end is None and cap_end is not None:
            stop = min(stop, cap_end)
        total += max(0.0, (stop - start).total_seconds())
    return min(total, PERIOD_MINUTES * 60.0)


# ---------------------------------------------------------------- database helpers
_subj_cache: Dict[int, Tuple[float, set]] = {}


def takes_subject(student_id: int, subject_id: int) -> bool:
    """A student with subject enrolments only counts in those subjects' classes (no rows = section-wide)."""
    import time as _t
    hit = _subj_cache.get(student_id)
    if hit is None or _t.time() - hit[0] > 5:
        ids = {sid for (sid,) in db.session.query(StudentSubject.subject_id).filter_by(student_id=student_id)}
        hit = _subj_cache[student_id] = (_t.time(), ids)
    return not hit[1] or subject_id in hit[1]


def open_segment(record_id: int) -> Optional[ObservationInterval]:
    return (ObservationInterval.query.filter_by(record_id=record_id, end_time=None)
            .order_by(ObservationInterval.id.desc()).first())


def last_segment(record_id: int) -> Optional[ObservationInterval]:
    return ObservationInterval.query.filter_by(record_id=record_id).order_by(ObservationInterval.id.desc()).first()


def record_summary(record_ids: Iterable[int], session=None, now: Optional[datetime] = None) -> Dict[int, dict]:
    """{record_id: {entries, seconds, inside, entry, exit}} computed from the presence segments."""
    ids = list(record_ids)
    if not ids:
        return {}
    now = now or now_utc()
    cap = period_end(session) if session is not None else None
    rows = (db.session.query(ObservationInterval.record_id, ObservationInterval.start_time, ObservationInterval.end_time)
            .filter(ObservationInterval.record_id.in_(ids)).order_by(ObservationInterval.id).all())
    segs = defaultdict(list)
    for rid, st_, en_ in rows:
        segs[rid].append((aware(st_), aware(en_)))
    out = {}
    for rid, items in segs.items():
        inside = items[-1][1] is None
        out[rid] = {
            "entries": len(items),
            "seconds": total_seconds(items, now, cap),
            "inside": inside,
            "entry": items[0][0],
            "exit": None if inside else items[-1][1],
        }
    return out


def record_stats(record_ids: Iterable[int], session=None) -> Dict[int, Tuple[int, float]]:
    """{record_id: (entries, seconds)}"""
    return {rid: (v["entries"], v["seconds"]) for rid, v in record_summary(record_ids, session).items()}


def register_entry(record, now) -> bool:
    """Open a presence segment. False if the student is already inside (must press Exit first)."""
    if open_segment(record.id) is not None:
        return False
    db.session.add(ObservationInterval(record_id=record.id, start_time=now, end_time=None))
    record.last_seen_at = now
    if record.first_seen_at is None:
        record.first_seen_at = now
    return True


def register_exit(record, session, now) -> bool:
    """Close the open segment and apply the 20-minute rule. False if the student never entered / already exited."""
    seg = open_segment(record.id)
    if seg is None:
        return False
    seg.end_time = now
    record.last_seen_at = now
    db.session.flush()
    apply_rule(record, session, now)
    return True


def apply_rule(record, session, now=None):
    """Set seconds/minutes and status from the segments. A student who is inside right now stays present."""
    now = now or now_utc()
    s = record_summary([record.id], session, now).get(record.id)
    secs = s["seconds"] if s else 0.0
    record.total_observed_seconds = secs
    record.coverage_percentage = round(min(100.0, secs * 100.0 / (PERIOD_MINUTES * 60.0)), 1)
    if record.is_manually_modified:
        return
    if s and s["inside"]:
        record.status = "present"
    else:
        record.status = status_for_minutes(secs / 60.0)


def finalize_session(session: AttendanceSession, closed_by_id=None, reason="end_live_session") -> Tuple[int, int]:
    """Close a session. Open segments end with the class; students who never entered become absent;
    anyone under 20 minutes is absent. Returns (present, absent). Safe to call twice."""
    now = now_utc()
    close_at = min(now, period_end(session) or now)
    have = {sid for (sid,) in db.session.query(AttendanceRecord.student_id).filter_by(session_id=session.id)}
    for st in Student.query.filter_by(section_id=session.section_id).all():
        if st.id not in have and takes_subject(st.id, session.subject_id):
            db.session.add(AttendanceRecord(
                session_id=session.id, student_id=st.id, status="absent",
                total_observed_seconds=0.0, coverage_percentage=0.0, confidence_score=0.0))
    db.session.flush()

    records = AttendanceRecord.query.filter_by(session_id=session.id).all()
    ids = [r.id for r in records]
    if ids:
        for seg in ObservationInterval.query.filter(ObservationInterval.record_id.in_(ids),
                                                    ObservationInterval.end_time.is_(None)).all():
            seg.end_time = max(close_at, aware(seg.start_time))
        db.session.flush()
    present = absent = 0
    for r in records:
        apply_rule(r, session, now)
        if r.status in ("present", "late"):
            present += 1
        elif r.status == "absent":
            absent += 1

    session.status = "completed"
    session.camera_active = False
    session.end_time = session.end_time or now
    session.completed_at = now
    db.session.add(AuditLog(
        user_id=closed_by_id, action=reason, entity_type="AttendanceSession", entity_id=session.id,
        new_value=f"present={present}, absent={absent}"))
    return present, absent


def close_stale_sessions() -> int:
    """Sessions left open from a previous day, or open longer than the period + 15 min, are closed automatically."""
    stale = AttendanceSession.query.filter(AttendanceSession.status.in_(OPEN_STATUSES)).all()
    now = now_utc()
    closed = 0
    for s in stale:
        end = period_end(s)
        if s.date < date.today() or (end is not None and now > end + timedelta(minutes=15)):
            finalize_session(s, closed_by_id=None, reason="auto_close_session")
            closed += 1
    if closed:
        db.session.commit()
    return closed
