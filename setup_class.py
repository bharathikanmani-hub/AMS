"""Assign a faculty member to a subject + section, and put students into that section.

Safe to re-run: it reuses anything that already exists and never deletes data.

Example:
    python setup_class.py --faculty kumar@college.edu \
        --department-code CSE --department-name "Computer Science" \
        --section CSE-A --year 3 --semester 5 --academic-year 2026-27 \
        --subject-code CS501 --subject-name "Computer Vision" \
        --students 21CS001,21CS002,21CS003

Students listed in --students must already have signed up (Create account).
Their roll number must equal the folder name used in the face dataset
(dataset/<roll>/...) for face recognition to match them.
"""

import argparse
import sys

from app import create_app
from extensions import db
from models import Department, FacultySubjectMapping, Section, Student, Subject, User


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--faculty", required=True, help="faculty ID (number) or e-mail")
    p.add_argument("--department-code", required=True)
    p.add_argument("--department-name", required=True)
    p.add_argument("--section", required=True, help="e.g. CSE-A")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--semester", type=int, required=True)
    p.add_argument("--academic-year", required=True, help="e.g. 2026-27")
    p.add_argument("--subject-code", required=True)
    p.add_argument("--subject-name", required=True)
    p.add_argument("--students", default="", help="comma-separated roll numbers to add to the section")
    a = p.parse_args()

    app = create_app()
    with app.app_context():
        key = a.faculty.strip()
        if key.isdigit():
            faculty = User.query.filter(User.id == int(key), User.role.in_(["faculty", "hod"])).first()
        else:
            faculty = User.query.filter(db.func.lower(User.email) == key.lower(), User.role.in_(["faculty", "hod"])).first()
        if not faculty:
            print("No faculty/hod account with that ID or e-mail. Create one with create_staff.py first.")
            return 1

        dept = Department.query.filter_by(code=a.department_code).first()
        if not dept:
            dept = Department(code=a.department_code, name=a.department_name)
            db.session.add(dept)
            db.session.flush()

        section = Section.query.filter_by(name=a.section, department_id=dept.id, academic_year=a.academic_year).first()
        if not section:
            section = Section(name=a.section, department_id=dept.id, year=a.year, semester=a.semester, academic_year=a.academic_year)
            db.session.add(section)
            db.session.flush()

        subject = Subject.query.filter_by(code=a.subject_code).first()
        if not subject:
            subject = Subject(code=a.subject_code, name=a.subject_name, department_id=dept.id, semester=a.semester)
            db.session.add(subject)
            db.session.flush()

        mapping = FacultySubjectMapping.query.filter_by(
            faculty_id=faculty.id, subject_id=subject.id, section_id=section.id,
            academic_year=a.academic_year, semester=a.semester,
        ).first()
        if not mapping:
            db.session.add(FacultySubjectMapping(
                faculty_id=faculty.id, subject_id=subject.id, section_id=section.id,
                academic_year=a.academic_year, semester=a.semester,
            ))

        added, missing = 0, []
        for roll in [r.strip() for r in a.students.split(",") if r.strip()]:
            st = Student.query.filter(db.func.upper(Student.roll_number) == roll.upper()).first()
            if not st:
                missing.append(roll)
                continue
            st.section_id, st.department_id, st.year = section.id, dept.id, a.year
            added += 1

        db.session.commit()
        print(f"Faculty {faculty.email} -> {subject.code} / {section.name} ready. Students placed in section: {added}.")
        if missing:
            print("Not found (they must sign up first): " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
