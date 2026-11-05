"""HOD (Head of Department) Blueprint routes for AttendAI.

Provides department-level dashboard, attendance monitoring, student/faculty
tracking, reports, export features, and low-attendance alerts.
All routes strictly enforce role == 'hod' and restrict data access to the
HOD's assigned department (current_user.department_id).
"""

from __future__ import annotations

import csv
import io
import smtplib
from datetime import date, datetime, timezone
from email.message import EmailMessage
from functools import wraps
from typing import Any, Dict, List, Optional

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
from sqlalchemy import func

from extensions import db
from models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Department,
    FacultySubjectMapping,
    Notification,
    Section,
    Student,
    Subject,
    SystemSetting,
    User,
)

hod_bp = Blueprint('hod', __name__, url_prefix='/hod')


def hod_required(f):
    """Decorator to enforce that current user is authenticated and has HOD role."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'hod':
            abort(403)
        if not current_user.department_id:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


@hod_bp.before_request
def verify_hod_access():
    """Verify that every request to /hod is authenticated and belongs to an HOD."""
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if current_user.role != 'hod':
        abort(403)
    if not current_user.department_id:
        abort(403)


def get_low_attendance_threshold() -> float:
    """Retrieve system low-attendance threshold (default 75.0%)."""
    setting = SystemSetting.query.filter_by(key='low_attendance_threshold').first()
    if setting and setting.value:
        try:
            return float(setting.value)
        except ValueError:
            pass
    return current_app.config.get('LOW_ATTENDANCE_THRESHOLD', 75.0)


def _safe_render_or_json(template_name: str, context: Dict[str, Any]):
    """Helper to render Jinja template with fallback to JSON if template is missing."""
    if request.is_json or request.headers.get('Accept') == 'application/json':
        clean_context = {}
        for k, v in context.items():
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                clean_context[k] = v
        return jsonify(clean_context)
    try:
        return render_template(template_name, **context)
    except Exception:
        # Fallback to JSON response if template file not yet present
        clean_context = {}
        for k, v in context.items():
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                clean_context[k] = v
        return jsonify(clean_context)


# ============================================================================
# 1. HOD DASHBOARD
# ============================================================================
@hod_bp.route('/')
@hod_bp.route('/dashboard')
@hod_required
def dashboard():
    """HOD dashboard with aggregated department stats."""
    dept_id = current_user.department_id
    dept = Department.query.filter_by(id=dept_id).first_or_404()
    threshold = get_low_attendance_threshold()

    # 1. Overall Department Attendance %
    total_records = (
        db.session.query(func.count(AttendanceRecord.id))
        .join(Student, AttendanceRecord.student_id == Student.id)
        .filter(Student.department_id == dept_id)
        .scalar() or 0
    )
    present_records = (
        db.session.query(func.count(AttendanceRecord.id))
        .join(Student, AttendanceRecord.student_id == Student.id)
        .filter(Student.department_id == dept_id, AttendanceRecord.status == 'present')
        .scalar() or 0
    )
    dept_attendance_pct = round((present_records / total_records * 100.0), 2) if total_records > 0 else 0.0

    # 2. Section-wise Attendance
    sections = Section.query.filter_by(department_id=dept_id).order_by(Section.year, Section.semester, Section.name).all()
    section_stats = []
    for sec in sections:
        sec_total = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(Student, AttendanceRecord.student_id == Student.id)
            .filter(Student.department_id == dept_id, Student.section_id == sec.id)
            .scalar() or 0
        )
        sec_present = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(Student, AttendanceRecord.student_id == Student.id)
            .filter(Student.department_id == dept_id, Student.section_id == sec.id, AttendanceRecord.status == 'present')
            .scalar() or 0
        )
        sec_pct = round((sec_present / sec_total * 100.0), 2) if sec_total > 0 else 0.0
        student_count = Student.query.filter_by(department_id=dept_id, section_id=sec.id).count()
        section_stats.append({
            'section_id': sec.id,
            'name': sec.name,
            'year': sec.year,
            'semester': sec.semester,
            'academic_year': sec.academic_year,
            'student_count': student_count,
            'total_records': sec_total,
            'present_records': sec_present,
            'attendance_percentage': sec_pct,
        })

    # 3. Subject-wise Attendance
    subjects = Subject.query.filter_by(department_id=dept_id).order_by(Subject.semester, Subject.code).all()
    subject_stats = []
    for sub in subjects:
        sub_total = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .filter(AttendanceSession.subject_id == sub.id)
            .scalar() or 0
        )
        sub_present = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .filter(AttendanceSession.subject_id == sub.id, AttendanceRecord.status == 'present')
            .scalar() or 0
        )
        sub_pct = round((sub_present / sub_total * 100.0), 2) if sub_total > 0 else 0.0
        sessions_count = AttendanceSession.query.filter_by(subject_id=sub.id).count()
        subject_stats.append({
            'subject_id': sub.id,
            'code': sub.code,
            'name': sub.name,
            'semester': sub.semester,
            'credits': sub.credits,
            'sessions_count': sessions_count,
            'total_records': sub_total,
            'present_records': sub_present,
            'attendance_percentage': sub_pct,
        })

    # 4. Students Below Threshold
    dept_students = Student.query.filter_by(department_id=dept_id).all()
    low_attendance_students = []
    for stu in dept_students:
        s_total = AttendanceRecord.query.filter_by(student_id=stu.id).count()
        s_present = AttendanceRecord.query.filter_by(student_id=stu.id, status='present').count()
        s_pct = round((s_present / s_total * 100.0), 2) if s_total > 0 else 100.0
        if s_total > 0 and s_pct < threshold:
            low_attendance_students.append({
                'id': stu.id,
                'roll_number': stu.roll_number,
                'name': stu.user.name if stu.user else 'Unknown',
                'email': stu.user.email if stu.user else '',
                'section': stu.section.name if stu.section else 'N/A',
                'year': stu.year,
                'total_classes': s_total,
                'attended_classes': s_present,
                'attendance_percentage': s_pct,
            })
    low_attendance_students.sort(key=lambda x: x['attendance_percentage'])

    # 5. Faculty Performance Summary
    faculty_list = User.query.filter_by(department_id=dept_id, role='faculty').all()
    faculty_summary = []
    for fac in faculty_list:
        fac_sessions = AttendanceSession.query.filter_by(faculty_id=fac.id).count()
        fac_records = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .filter(AttendanceSession.faculty_id == fac.id)
            .scalar() or 0
        )
        fac_present = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .filter(AttendanceSession.faculty_id == fac.id, AttendanceRecord.status == 'present')
            .scalar() or 0
        )
        fac_pct = round((fac_present / fac_records * 100.0), 2) if fac_records > 0 else 0.0
        mappings_count = FacultySubjectMapping.query.filter_by(faculty_id=fac.id).count()
        faculty_summary.append({
            'faculty_id': fac.id,
            'name': fac.name,
            'email': fac.email,
            'phone': fac.phone or 'N/A',
            'assigned_courses': mappings_count,
            'sessions_conducted': fac_sessions,
            'avg_class_attendance': fac_pct,
        })

    context = {
        'department': {
            'id': dept.id,
            'name': dept.name,
            'code': dept.code,
        },
        'stats': {
            'total_students': len(dept_students),
            'total_faculty': len(faculty_list),
            'total_sections': len(sections),
            'total_subjects': len(subjects),
            'department_attendance_percentage': dept_attendance_pct,
            'low_attendance_count': len(low_attendance_students),
            'threshold': threshold,
        },
        'section_stats': section_stats,
        'subject_stats': subject_stats,
        'low_attendance_students': low_attendance_students,
        'faculty_summary': faculty_summary,
    }
    return _safe_render_or_json('hod/dashboard.html', context)


# ============================================================================
# 2. DEPARTMENT ATTENDANCE RECORDS
# ============================================================================
@hod_bp.route('/attendance')
@hod_required
def attendance():
    """Department attendance records with date/section/subject filters."""
    dept_id = current_user.department_id

    # Filters
    date_str = request.args.get('date', '').strip()
    section_id = request.args.get('section_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    status = request.args.get('status', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 30, type=int)

    query = (
        db.session.query(AttendanceRecord)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(Student.department_id == dept_id)
    )

    # Date filter
    if date_str:
        try:
            filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            query = query.filter(AttendanceSession.date == filter_date)
        except ValueError:
            pass

    # Section filter (guaranteed inside this department)
    if section_id:
        sec = Section.query.filter_by(id=section_id, department_id=dept_id).first()
        if sec:
            query = query.filter(Student.section_id == section_id)

    # Subject filter (guaranteed inside this department)
    if subject_id:
        sub = Subject.query.filter_by(id=subject_id, department_id=dept_id).first()
        if sub:
            query = query.filter(AttendanceSession.subject_id == subject_id)

    # Status filter
    if status in ('present', 'absent', 'late', 'needs_review', 'excused'):
        query = query.filter(AttendanceRecord.status == status)

    query = query.order_by(AttendanceSession.date.desc(), AttendanceSession.period_number.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    records_data = []
    for rec in pagination.items:
        session = rec.session
        student = rec.student
        records_data.append({
            'record_id': rec.id,
            'session_id': rec.session_id,
            'date': session.date.strftime('%Y-%m-%d') if session and session.date else 'N/A',
            'period': session.period_number if session else 0,
            'subject_code': session.subject.code if session and session.subject else 'N/A',
            'subject_name': session.subject.name if session and session.subject else 'N/A',
            'student_id': student.id if student else 0,
            'roll_number': student.roll_number if student else 'N/A',
            'student_name': student.user.name if student and student.user else 'Unknown',
            'section': student.section.name if student and student.section else 'N/A',
            'status': rec.status,
            'coverage_percentage': round(rec.coverage_percentage, 1),
            'confidence_score': round(rec.confidence_score, 2),
            'is_manually_modified': rec.is_manually_modified,
            'modification_reason': rec.modification_reason or '',
        })

    sections = Section.query.filter_by(department_id=dept_id).order_by(Section.name).all()
    subjects = Subject.query.filter_by(department_id=dept_id).order_by(Subject.code).all()

    context = {
        'records': records_data,
        'page': pagination.page,
        'pages': pagination.pages,
        'total': pagination.total,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
        'sections': [{'id': s.id, 'name': s.name} for s in sections],
        'subjects': [{'id': s.id, 'code': s.code, 'name': s.name} for s in subjects],
        'current_filters': {
            'date': date_str,
            'section_id': section_id,
            'subject_id': subject_id,
            'status': status,
        },
    }
    return _safe_render_or_json('hod/attendance.html', context)


# ============================================================================
# 3. LIST STUDENTS IN DEPARTMENT
# ============================================================================
@hod_bp.route('/students')
@hod_required
def students():
    """List students in department with attendance statistics."""
    dept_id = current_user.department_id
    search_q = request.args.get('q', '').strip()
    section_id = request.args.get('section_id', type=int)

    query = Student.query.join(User).filter(Student.department_id == dept_id)

    if search_q:
        search_filter = f"%{search_q}%"
        query = query.filter(
            (Student.roll_number.ilike(search_filter)) |
            (User.name.ilike(search_filter)) |
            (User.email.ilike(search_filter))
        )

    if section_id:
        query = query.filter(Student.section_id == section_id)

    students_list = query.order_by(Student.roll_number).all()

    student_stats = []
    threshold = get_low_attendance_threshold()
    for stu in students_list:
        total = AttendanceRecord.query.filter_by(student_id=stu.id).count()
        present = AttendanceRecord.query.filter_by(student_id=stu.id, status='present').count()
        pct = round((present / total * 100.0), 2) if total > 0 else 100.0
        student_stats.append({
            'id': stu.id,
            'roll_number': stu.roll_number,
            'admission_number': stu.admission_number or '',
            'name': stu.user.name if stu.user else 'Unknown',
            'email': stu.user.email if stu.user else '',
            'phone': stu.user.phone if stu.user else '',
            'year': stu.year,
            'section': stu.section.name if stu.section else 'N/A',
            'total_classes': total,
            'attended_classes': present,
            'attendance_percentage': pct,
            'is_low': pct < threshold if total > 0 else False,
        })

    sections = Section.query.filter_by(department_id=dept_id).order_by(Section.name).all()
    context = {
        'students': student_stats,
        'sections': [{'id': s.id, 'name': s.name} for s in sections],
        'total_count': len(student_stats),
        'search_query': search_q,
        'selected_section_id': section_id,
        'threshold': threshold,
    }
    return _safe_render_or_json('hod/students.html', context)


# ============================================================================
# 4. STUDENT DETAIL WITH ATTENDANCE HISTORY
# ============================================================================
@hod_bp.route('/students/<int:id>')
@hod_required
def student_detail(id: int):
    """Student detail with attendance history.

    MUST verify student belongs to HOD's department.
    """
    dept_id = current_user.department_id
    student = Student.query.filter_by(id=id, department_id=dept_id).first()
    if not student:
        abort(404, description="Student not found in your department.")

    # Attendance summary
    total_records = AttendanceRecord.query.filter_by(student_id=student.id).count()
    present_records = AttendanceRecord.query.filter_by(student_id=student.id, status='present').count()
    overall_pct = round((present_records / total_records * 100.0), 2) if total_records > 0 else 100.0

    # Subject-wise attendance breakdown
    dept_subjects = Subject.query.filter_by(department_id=dept_id).all()
    subject_breakdown = []
    for sub in dept_subjects:
        sub_total = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .filter(AttendanceRecord.student_id == student.id, AttendanceSession.subject_id == sub.id)
            .scalar() or 0
        )
        if sub_total > 0:
            sub_present = (
                db.session.query(func.count(AttendanceRecord.id))
                .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
                .filter(
                    AttendanceRecord.student_id == student.id,
                    AttendanceSession.subject_id == sub.id,
                    AttendanceRecord.status == 'present',
                )
                .scalar() or 0
            )
            sub_pct = round((sub_present / sub_total * 100.0), 2)
            subject_breakdown.append({
                'subject_id': sub.id,
                'code': sub.code,
                'name': sub.name,
                'total_classes': sub_total,
                'attended_classes': sub_present,
                'percentage': sub_pct,
            })

    # Detailed history (latest 50 records)
    records = (
        AttendanceRecord.query
        .join(AttendanceSession)
        .filter(AttendanceRecord.student_id == student.id)
        .order_by(AttendanceSession.date.desc(), AttendanceSession.period_number.desc())
        .limit(50)
        .all()
    )

    history = []
    for r in records:
        sess = r.session
        history.append({
            'record_id': r.id,
            'session_id': r.session_id,
            'date': sess.date.strftime('%Y-%m-%d') if sess and sess.date else 'N/A',
            'period': sess.period_number if sess else 0,
            'subject_code': sess.subject.code if sess and sess.subject else 'N/A',
            'subject_name': sess.subject.name if sess and sess.subject else 'N/A',
            'faculty_name': sess.faculty.name if sess and sess.faculty else 'N/A',
            'status': r.status,
            'coverage_percentage': round(r.coverage_percentage, 1),
            'confidence_score': round(r.confidence_score, 2),
            'is_manually_modified': r.is_manually_modified,
            'modification_reason': r.modification_reason or '',
        })

    context = {
        'student': {
            'id': student.id,
            'roll_number': student.roll_number,
            'admission_number': student.admission_number,
            'name': student.user.name if student.user else 'Unknown',
            'email': student.user.email if student.user else '',
            'phone': student.user.phone if student.user else '',
            'year': student.year,
            'section': student.section.name if student.section else 'N/A',
            'department': student.department.name if student.department else 'N/A',
        },
        'overall_stats': {
            'total_classes': total_records,
            'attended_classes': present_records,
            'percentage': overall_pct,
        },
        'subject_breakdown': subject_breakdown,
        'history': history,
    }
    return _safe_render_or_json('hod/student_detail.html', context)


# ============================================================================
# 5. LIST FACULTY IN DEPARTMENT
# ============================================================================
@hod_bp.route('/faculty')
@hod_required
def faculty():
    """List all faculty members in HOD's department."""
    dept_id = current_user.department_id
    faculty_members = (
        User.query
        .filter_by(department_id=dept_id, role='faculty')
        .order_by(User.name)
        .all()
    )

    faculty_data = []
    for fac in faculty_members:
        mappings = FacultySubjectMapping.query.filter_by(faculty_id=fac.id).all()
        assigned_subjects = [
            f"{m.subject.code} ({m.section.name})" for m in mappings if m.subject and m.section
        ]
        total_sessions = AttendanceSession.query.filter_by(faculty_id=fac.id).count()
        last_session = (
            AttendanceSession.query
            .filter_by(faculty_id=fac.id)
            .order_by(AttendanceSession.created_at.desc())
            .first()
        )
        faculty_data.append({
            'id': fac.id,
            'name': fac.name,
            'email': fac.email,
            'phone': fac.phone or 'N/A',
            'assigned_subjects': assigned_subjects,
            'sessions_count': total_sessions,
            'last_active': (
                last_session.created_at.strftime('%Y-%m-%d %H:%M')
                if last_session and last_session.created_at else 'Never'
            ),
        })

    context = {
        'faculty': faculty_data,
        'total_count': len(faculty_data),
    }
    return _safe_render_or_json('hod/faculty.html', context)


# ============================================================================
# 6. REPORTS PAGE WITH DEPARTMENT-SCOPE FILTERS
# ============================================================================
@hod_bp.route('/reports')
@hod_required
def reports():
    """Reports page with department-scoped date, section, and subject filters."""
    dept_id = current_user.department_id
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    section_id = request.args.get('section_id', type=int)
    subject_id = request.args.get('subject_id', type=int)

    query = (
        db.session.query(AttendanceRecord)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(Student.department_id == dept_id)
    )

    if start_date_str:
        try:
            s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(AttendanceSession.date >= s_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            e_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(AttendanceSession.date <= e_date)
        except ValueError:
            pass

    if section_id:
        if Section.query.filter_by(id=section_id, department_id=dept_id).first():
            query = query.filter(Student.section_id == section_id)

    if subject_id:
        if Subject.query.filter_by(id=subject_id, department_id=dept_id).first():
            query = query.filter(AttendanceSession.subject_id == subject_id)

    total_records = query.count()
    present_records = query.filter(AttendanceRecord.status == 'present').count()
    avg_percentage = round((present_records / total_records * 100.0), 2) if total_records > 0 else 0.0

    sections = Section.query.filter_by(department_id=dept_id).order_by(Section.name).all()
    subjects = Subject.query.filter_by(department_id=dept_id).order_by(Subject.code).all()

    context = {
        'summary': {
            'total_records': total_records,
            'present_records': present_records,
            'absent_records': total_records - present_records,
            'average_percentage': avg_percentage,
        },
        'sections': [{'id': s.id, 'name': s.name} for s in sections],
        'subjects': [{'id': s.id, 'code': s.code, 'name': s.name} for s in subjects],
        'filters': {
            'start_date': start_date_str,
            'end_date': end_date_str,
            'section_id': section_id,
            'subject_id': subject_id,
        },
    }
    return _safe_render_or_json('hod/reports.html', context)


# ============================================================================
# 7. EXPORT DEPARTMENT CSV
# ============================================================================
@hod_bp.route('/reports/export/csv')
@hod_required
def export_csv():
    """Export department attendance records to CSV."""
    dept_id = current_user.department_id
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    section_id = request.args.get('section_id', type=int)
    subject_id = request.args.get('subject_id', type=int)

    query = (
        db.session.query(AttendanceRecord)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(Student.department_id == dept_id)
    )

    if start_date_str:
        try:
            query = query.filter(AttendanceSession.date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
        except ValueError:
            pass
    if end_date_str:
        try:
            query = query.filter(AttendanceSession.date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())
        except ValueError:
            pass
    if section_id and Section.query.filter_by(id=section_id, department_id=dept_id).first():
        query = query.filter(Student.section_id == section_id)
    if subject_id and Subject.query.filter_by(id=subject_id, department_id=dept_id).first():
        query = query.filter(AttendanceSession.subject_id == subject_id)

    records = query.order_by(AttendanceSession.date.desc(), AttendanceSession.period_number.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date',
        'Period',
        'Subject Code',
        'Subject Name',
        'Section',
        'Roll Number',
        'Student Name',
        'Status',
        'Manual Edit',
        'Reason',
    ])

    for rec in records:
        sess = rec.session
        stu = rec.student
        writer.writerow([
            sess.date.strftime('%Y-%m-%d') if sess and sess.date else '',
            sess.period_number if sess else '',
            sess.subject.code if sess and sess.subject else '',
            sess.subject.name if sess and sess.subject else '',
            stu.section.name if stu and stu.section else '',
            stu.roll_number if stu else '',
            stu.user.name if stu and stu.user else '',
            rec.status.title(),
            'Yes' if rec.is_manually_modified else 'No',
            rec.modification_reason or '',
        ])

    csv_data = output.getvalue()
    dept = Department.query.get(dept_id)
    filename = f"{dept.code if dept else 'dept'}_attendance_{date.today().strftime('%Y%m%d')}.csv"

    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


# ============================================================================
# 8. EXPORT DEPARTMENT EXCEL
# ============================================================================
@hod_bp.route('/reports/export/excel')
@hod_required
def export_excel():
    """Export department attendance records to Excel format."""
    dept_id = current_user.department_id
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    section_id = request.args.get('section_id', type=int)
    subject_id = request.args.get('subject_id', type=int)

    query = (
        db.session.query(AttendanceRecord)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(Student.department_id == dept_id)
    )

    if start_date_str:
        try:
            query = query.filter(AttendanceSession.date >= datetime.strptime(start_date_str, '%Y-%m-%d').date())
        except ValueError:
            pass
    if end_date_str:
        try:
            query = query.filter(AttendanceSession.date <= datetime.strptime(end_date_str, '%Y-%m-%d').date())
        except ValueError:
            pass
    if section_id and Section.query.filter_by(id=section_id, department_id=dept_id).first():
        query = query.filter(Student.section_id == section_id)
    if subject_id and Subject.query.filter_by(id=subject_id, department_id=dept_id).first():
        query = query.filter(AttendanceSession.subject_id == subject_id)

    records = query.order_by(AttendanceSession.date.desc(), AttendanceSession.period_number.asc()).all()

    dept = Department.query.get(dept_id)
    dept_code = dept.code if dept else 'dept'

    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Attendance Report"

        headers = [
            'Date', 'Period', 'Subject Code', 'Subject Name',
            'Section', 'Roll Number', 'Student Name', 'Status',
            'Manual Edit', 'Reason'
        ]
        ws.append(headers)

        for rec in records:
            sess = rec.session
            stu = rec.student
            ws.append([
                sess.date.strftime('%Y-%m-%d') if sess and sess.date else '',
                sess.period_number if sess else '',
                sess.subject.code if sess and sess.subject else '',
                sess.subject.name if sess and sess.subject else '',
                stu.section.name if stu and stu.section else '',
                stu.roll_number if stu else '',
                stu.user.name if stu and stu.user else '',
                rec.status.title(),
                'Yes' if rec.is_manually_modified else 'No',
                rec.modification_reason or '',
            ])

        stream = io.BytesIO()
        wb.save(stream)
        stream.seek(0)
        filename = f"{dept_code}_attendance_{date.today().strftime('%Y%m%d')}.xlsx"
        return Response(
            stream.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    except ImportError:
        # Fallback to CSV if openpyxl is not installed
        return export_csv()


# ============================================================================
# 9. LOW ATTENDANCE ALERTS
# ============================================================================
@hod_bp.route('/alerts')
@hod_required
def alerts():
    """List students in department with attendance below threshold."""
    dept_id = current_user.department_id
    threshold = get_low_attendance_threshold()

    students = Student.query.filter_by(department_id=dept_id).all()
    alert_students = []

    for stu in students:
        total = AttendanceRecord.query.filter_by(student_id=stu.id).count()
        present = AttendanceRecord.query.filter_by(student_id=stu.id, status='present').count()
        pct = round((present / total * 100.0), 2) if total > 0 else 100.0
        if total > 0 and pct < threshold:
            alert_students.append({
                'student_id': stu.id,
                'roll_number': stu.roll_number,
                'name': stu.user.name if stu.user else 'Unknown',
                'email': stu.user.email if stu.user else '',
                'phone': stu.user.phone if stu.user else '',
                'section': stu.section.name if stu.section else 'N/A',
                'year': stu.year,
                'total_classes': total,
                'attended_classes': present,
                'missed_classes': total - present,
                'attendance_percentage': pct,
            })

    alert_students.sort(key=lambda x: x['attendance_percentage'])
    context = {
        'threshold': threshold,
        'alert_students': alert_students,
        'total_alerts': len(alert_students),
    }
    return _safe_render_or_json('hod/alerts.html', context)


# ============================================================================
# 10. SEND ATTENDANCE ALERTS VIA EMAIL
# ============================================================================
@hod_bp.route('/alerts/send', methods=['POST'])
@hod_required
def send_alerts():
    """Send low-attendance email alerts to students in this department."""
    dept_id = current_user.department_id
    threshold = get_low_attendance_threshold()

    data = request.get_json(silent=True) or {}
    student_ids = data.get('student_ids') or request.form.getlist('student_ids', type=int)

    # If student_ids not provided, find all low attendance students in dept
    if not student_ids:
        all_students = Student.query.filter_by(department_id=dept_id).all()
        target_students = []
        for s in all_students:
            t = AttendanceRecord.query.filter_by(student_id=s.id).count()
            p = AttendanceRecord.query.filter_by(student_id=s.id, status='present').count()
            if t > 0 and (p / t * 100.0) < threshold:
                target_students.append(s)
    else:
        # Strictly verify each student ID belongs to HOD's department
        target_students = Student.query.filter(
            Student.id.in_(student_ids),
            Student.department_id == dept_id,
        ).all()

    if not target_students:
        msg = "No eligible students found in your department to alert."
        if request.is_json:
            return jsonify({'message': msg, 'sent_count': 0}), 200
        flash(msg, 'info')
        return redirect(url_for('hod.alerts'))

    mail_email = current_app.config.get('MAIL_EMAIL', '')
    mail_password = current_app.config.get('MAIL_APP_PASSWORD', '')
    smtp_host = current_app.config.get('MAIL_SMTP_HOST', 'smtp.gmail.com')
    smtp_port = current_app.config.get('MAIL_SMTP_PORT', 587)

    has_smtp = bool(mail_email and mail_password)
    sent_count = 0
    failed_count = 0

    dept = Department.query.get(dept_id)
    dept_name = dept.name if dept else "Your Department"

    for stu in target_students:
        email = stu.user.email if stu.user else ''
        if not email:
            continue

        tot = AttendanceRecord.query.filter_by(student_id=stu.id).count()
        pres = AttendanceRecord.query.filter_by(student_id=stu.id, status='present').count()
        pct = round((pres / tot * 100.0), 2) if tot > 0 else 0.0

        subject_line = f"Important: Low Attendance Warning - AttendAI ({pct}%)"
        body = (
            f"Dear {stu.user.name if stu.user else 'Student'},\n\n"
            f"This is an automated notification from the Department of {dept_name}.\n"
            f"Your current cumulative attendance is {pct}%, which is below the minimum "
            f"mandatory threshold of {threshold}%.\n\n"
            f"Total classes recorded: {tot}\n"
            f"Classes attended: {pres}\n"
            f"Classes missed: {tot - pres}\n\n"
            f"Please meet with your HOD or academic advisor immediately to rectify this.\n\n"
            f"Regards,\n"
            f"Department of {dept_name}\nAttendAI Automated System"
        )

        notification = Notification(
            student_id=stu.id,
            type='low_attendance',
            subject=subject_line,
            message=body,
            email=email,
            status='pending',
            sent_at=datetime.now(timezone.utc),
        )
        db.session.add(notification)
        db.session.flush()

        if has_smtp:
            try:
                msg = EmailMessage()
                msg['Subject'] = subject_line
                msg['From'] = mail_email
                msg['To'] = email
                msg.set_content(body)

                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(mail_email, mail_password)
                    server.send_message(msg)

                notification.status = 'sent'
                sent_count += 1
            except Exception as e:
                notification.status = 'failed'
                notification.error_message = str(e)
                failed_count += 1
        else:
            notification.status = 'not_configured'
            notification.error_message = "SMTP credentials not configured."
            sent_count += 1  # Logged in notifications database

    # Audit log entry for alert dispatch
    audit = AuditLog(
        user_id=current_user.id,
        action='send_low_attendance_alerts',
        entity_type='Notification',
        entity_id=dept_id,
        reason=f"Dispatched low attendance warnings to {len(target_students)} students.",
        ip_address=request.remote_addr,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(audit)
    db.session.commit()

    result_msg = f"Alert process completed: {sent_count} recorded/sent, {failed_count} failed."
    if request.is_json:
        return jsonify({
            'message': result_msg,
            'sent_count': sent_count,
            'failed_count': failed_count,
            'smtp_configured': has_smtp,
        }), 200

    flash(result_msg, 'success' if failed_count == 0 else 'warning')
    return redirect(url_for('hod.alerts'))
