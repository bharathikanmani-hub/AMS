"""Fill the timetable with more periods and give Gayathri more subjects.  Safe to re-run (adds only what is missing).

    python add_periods_subjects.py
    python add_periods_subjects.py --student Gayathri --extra "Machine Learning,Computer Networks,Software Engineering"

* Every section gets periods 1-8, Monday-Friday, by cycling the subjects/faculty already assigned to it
  (a faculty member is never double-booked).
* The named student gets the extra subjects (taught by faculty already in her section) on top of her current ones.
* Every student already in a section is recorded as taking that section's current subjects, so attendance in a
  subject is marked only in that subject's class.
"""
import argparse
from datetime import time

from app import create_app
from extensions import db
from models import (Classroom, FacultySubjectMapping, Section, Student, StudentSubject, Subject, Timetable, User)
from routes.api_admin import _find_or_create_subject

# 45-minute periods (10-minute break after periods 2 and 6 would be easy to add; kept simple)
PERIODS = [(1, time(9, 0), time(9, 45)), (2, time(9, 45), time(10, 30)), (3, time(10, 40), time(11, 25)),
           (4, time(11, 25), time(12, 10)), (5, time(13, 10), time(13, 55)), (6, time(13, 55), time(14, 40)),
           (7, time(14, 50), time(15, 35)), (8, time(15, 35), time(16, 20))]


def busy(fac_id, day, start, end):
    return (db.session.query(Timetable).join(FacultySubjectMapping, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
            .filter(FacultySubjectMapping.faculty_id == fac_id, Timetable.day_of_week == day, Timetable.is_active.is_(True),
                    Timetable.start_time < end, start < Timetable.end_time).first() is not None)


def fill_periods(section):
    maps = FacultySubjectMapping.query.filter_by(section_id=section.id).order_by(FacultySubjectMapping.id).all()
    if not maps:
        return 0
    first = (db.session.query(Timetable.classroom_id).join(FacultySubjectMapping, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
             .filter(FacultySubjectMapping.section_id == section.id, Timetable.classroom_id.isnot(None)).first())
    room_id = first[0] if first else None
    if room_id is None:
        room = Classroom.query.filter_by(room_number="R-101").first() or Classroom(room_number="R-101", department_id=section.department_id)
        db.session.add(room); db.session.flush(); room_id = room.id
    added, k = 0, 0
    for day in range(5):
        for no, start, end in PERIODS:
            taken = (db.session.query(Timetable).join(FacultySubjectMapping, Timetable.faculty_subject_mapping_id == FacultySubjectMapping.id)
                     .filter(FacultySubjectMapping.section_id == section.id, Timetable.day_of_week == day,
                             Timetable.period_number == no, Timetable.is_active.is_(True)).first())
            if taken:
                continue
            for _ in range(len(maps)):               # next subject whose faculty is free at this time
                m = maps[k % len(maps)]; k += 1
                if not busy(m.faculty_id, day, start, end):
                    db.session.add(Timetable(faculty_subject_mapping_id=m.id, classroom_id=room_id, day_of_week=day,
                                             period_number=no, start_time=start, end_time=end, is_active=True))
                    db.session.flush(); added += 1
                    break
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--student", default="Gayathri")
    ap.add_argument("--extra", default="Machine Learning,Computer Networks,Software Engineering,Database Management Systems")
    a = ap.parse_args()
    app = create_app()
    with app.app_context():
        # 1) everyone in a section takes the section's existing subjects
        for sec in Section.query.all():
            sids = {m.subject_id for m in FacultySubjectMapping.query.filter_by(section_id=sec.id)}
            for st in Student.query.filter_by(section_id=sec.id):
                have = {r.subject_id for r in StudentSubject.query.filter_by(student_id=st.id)}
                for sid in sids - have:
                    db.session.add(StudentSubject(student_id=st.id, subject_id=sid))
        db.session.commit()

        # 2) extra subjects for the named student
        st = (Student.query.join(User, User.id == Student.user_id).filter(db.func.lower(User.name).like(a.student.lower() + "%")).first())
        if st is None or st.section_id is None:
            print(f"Student '{a.student}' not found or has no section - skipped the extra subjects.")
        else:
            sec = db.session.get(Section, st.section_id)
            fac_ids = [m.faculty_id for m in FacultySubjectMapping.query.filter_by(section_id=sec.id)]
            fac_ids = list(dict.fromkeys(fac_ids)) or [u.id for u in User.query.filter(User.role.in_(("faculty", "hod")))]
            for i, name in enumerate([n.strip() for n in a.extra.split(",") if n.strip()]):
                if not fac_ids:
                    print("No faculty exist yet - add faculty first."); break
                subj = _find_or_create_subject(name, sec)
                if not FacultySubjectMapping.query.filter_by(subject_id=subj.id, section_id=sec.id).first():
                    db.session.add(FacultySubjectMapping(faculty_id=fac_ids[i % len(fac_ids)], subject_id=subj.id, section_id=sec.id,
                                                         academic_year=sec.academic_year, semester=sec.semester))
                if not StudentSubject.query.filter_by(student_id=st.id, subject_id=subj.id).first():
                    db.session.add(StudentSubject(student_id=st.id, subject_id=subj.id))
            db.session.commit()
            print(f"{a.student}: now has {StudentSubject.query.filter_by(student_id=st.id).count()} subjects.")

        # 3) more periods
        total = sum(fill_periods(sec) for sec in Section.query.all())
        db.session.commit()
        print(f"Added {total} timetable periods.")


if __name__ == "__main__":
    main()
