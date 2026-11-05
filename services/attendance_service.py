"""Attendance calculation and finalization service."""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Tuple, Optional

from extensions import db
from models import (
    AttendanceSession, AttendanceRecord, ObservationInterval,
    Student, AuditLog, Notification, SystemSetting
)

logger = logging.getLogger(__name__)


def calculate_observed_duration(record_id: int) -> float:
    """Calculate total non-overlapping observed seconds for a record.
    
    Merges overlapping intervals to avoid double-counting.
    Returns total seconds.
    """
    intervals = ObservationInterval.query.filter_by(
        record_id=record_id
    ).order_by(ObservationInterval.start_time).all()
    
    if not intervals:
        return 0.0
    
    # Merge overlapping intervals
    merged = []
    current_start = intervals[0].start_time
    current_end = intervals[0].end_time
    
    for iv in intervals[1:]:
        if iv.start_time <= current_end + timedelta(seconds=5):  # 5s tolerance
            current_end = max(current_end, iv.end_time)
        else:
            merged.append((current_start, current_end))
            current_start = iv.start_time
            current_end = iv.end_time
    merged.append((current_start, current_end))
    
    total_seconds = sum(
        (end - start).total_seconds() for start, end in merged
    )
    return max(total_seconds, 0.0)


def calculate_coverage_percentage(
    observed_seconds: float,
    scheduled_duration_minutes: int
) -> float:
    """Calculate attendance coverage percentage.
    
    Coverage = observed_seconds / (scheduled_duration_minutes * 60) * 100
    """
    if scheduled_duration_minutes <= 0:
        return 0.0
    scheduled_seconds = scheduled_duration_minutes * 60
    return min((observed_seconds / scheduled_seconds) * 100, 100.0)


def determine_status(
    coverage_percentage: float,
    coverage_threshold: float,
    first_seen_at: Optional[datetime],
    session_start: Optional[datetime],
    late_threshold_minutes: int = 10
) -> str:
    """Determine attendance status based on coverage and timing.
    
    Args:
        coverage_percentage: % of period the student was observed
        coverage_threshold: minimum % to be marked Present (e.g., 70.0)
        first_seen_at: when student was first recognized
        session_start: when the session started
        late_threshold_minutes: minutes after start to be considered late
    
    Returns:
        'present', 'absent', 'late', or 'needs_review'
    """
    if coverage_percentage < coverage_threshold * 100:
        if coverage_percentage > 0:
            return 'needs_review'  # Some presence but not enough
        return 'absent'
    
    # Check if late
    if first_seen_at and session_start:
        diff = (first_seen_at - session_start).total_seconds()
        if diff > late_threshold_minutes * 60:
            return 'late'
    
    return 'present'


def finalize_session(session_id: int, finalized_by_id: int, coverage_threshold: float = 0.70) -> Tuple[bool, str]:
    """Finalize an attendance session.
    
    1. Calculate observed duration for each student record
    2. Apply coverage threshold (default 70%)
    3. Mark unobserved students as absent
    4. Update session status to completed
    5. Create audit log
    
    Returns (success, message)
    """
    session = db.session.get(AttendanceSession, session_id)
    if not session:
        return False, 'Session not found'
    
    if session.status == 'completed':
        return False, 'Session already finalized'
    
    try:
        scheduled_minutes = session.scheduled_duration_minutes or 60
        
        # Get all students in the section
        section_students = Student.query.filter_by(
            section_id=session.section_id
        ).all()
        
        student_ids_with_records = set()
        
        # Process existing records (students who were seen)
        records = AttendanceRecord.query.filter_by(session_id=session_id).all()
        for record in records:
            student_ids_with_records.add(record.student_id)
            
            # Calculate observed duration
            observed = calculate_observed_duration(record.id)
            record.total_observed_seconds = observed
            
            # Calculate coverage
            coverage = calculate_coverage_percentage(observed, scheduled_minutes)
            record.coverage_percentage = round(coverage, 2)
            
            # Determine status (only if not manually modified)
            if not record.is_manually_modified:
                record.status = determine_status(
                    coverage, coverage_threshold,
                    record.first_seen_at, session.start_time
                )
        
        # Create absent records for students not seen at all
        for student in section_students:
            if student.id not in student_ids_with_records:
                absent_record = AttendanceRecord(
                    session_id=session_id,
                    student_id=student.id,
                    status='absent',
                    total_observed_seconds=0,
                    coverage_percentage=0,
                    confidence_score=0,
                )
                db.session.add(absent_record)
        
        # Update session
        session.status = 'completed'
        session.completed_at = datetime.now(timezone.utc)
        session.camera_active = False
        
        # Audit log
        audit = AuditLog(
            user_id=finalized_by_id,
            action='finalize_session',
            entity_type='AttendanceSession',
            entity_id=session_id,
            new_value=f'Finalized with {len(records)} observed, {len(section_students) - len(student_ids_with_records)} absent'
        )
        db.session.add(audit)
        
        db.session.commit()
        
        present_count = sum(1 for r in records if r.status in ('present', 'late'))
        absent_count = len(section_students) - present_count
        
        return True, f'Session finalized: {present_count} present, {absent_count} absent'
    
    except Exception as e:
        db.session.rollback()
        logger.error('Error finalizing session %d: %s', session_id, e)
        return False, f'Error: {str(e)}'


def get_student_attendance_summary(student_id: int) -> dict:
    """Get overall attendance summary for a student."""
    records = AttendanceRecord.query.filter_by(student_id=student_id).all()
    
    total_sessions = len(records)
    present = sum(1 for r in records if r.status in ('present', 'late'))
    absent = sum(1 for r in records if r.status == 'absent')
    excused = sum(1 for r in records if r.status == 'excused')
    needs_review = sum(1 for r in records if r.status == 'needs_review')
    
    # Calculate percentage excluding excused
    countable = total_sessions - excused
    percentage = round((present / countable) * 100, 1) if countable > 0 else 0.0
    
    return {
        'total_sessions': total_sessions,
        'present': present,
        'absent': absent,
        'excused': excused,
        'needs_review': needs_review,
        'percentage': percentage,
    }


def get_subject_wise_attendance(student_id: int) -> list:
    """Get subject-wise attendance for a student."""
    from models import Subject
    from sqlalchemy import func
    
    results = db.session.query(
        Subject.id,
        Subject.name,
        Subject.code,
        func.count(AttendanceRecord.id).label('total'),
        func.sum(
            db.case(
                (AttendanceRecord.status.in_(['present', 'late']), 1),
                else_=0
            )
        ).label('present_count')
    ).join(
        AttendanceSession, AttendanceSession.subject_id == Subject.id
    ).join(
        AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id
    ).filter(
        AttendanceRecord.student_id == student_id
    ).group_by(
        Subject.id, Subject.name, Subject.code
    ).all()
    
    return [
        {
            'subject_id': r.id,
            'subject_name': r.name,
            'subject_code': r.code,
            'total_sessions': r.total,
            'present': r.present_count or 0,
            'percentage': round(((r.present_count or 0) / r.total) * 100, 1) if r.total > 0 else 0
        }
        for r in results
    ]
