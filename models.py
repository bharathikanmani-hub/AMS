"""Database models for AttendAI attendance management system."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db, login_manager


class User(UserMixin, db.Model):
    """User account model for authentication and role-based access control."""

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), nullable=False, index=True)  # admin, hod, faculty, student
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    department = db.relationship(
        'Department',
        foreign_keys=[department_id],
        back_populates='users',
    )
    hod_of_department = db.relationship(
        'Department',
        foreign_keys='Department.hod_id',
        back_populates='hod',
        uselist=False,
    )
    student_profile = db.relationship(
        'Student',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan',
    )
    faculty_mappings = db.relationship(
        'FacultySubjectMapping',
        foreign_keys='FacultySubjectMapping.faculty_id',
        back_populates='faculty',
        cascade='all, delete-orphan',
    )
    sessions_conducted = db.relationship(
        'AttendanceSession',
        foreign_keys='AttendanceSession.faculty_id',
        back_populates='faculty',
    )
    modified_records = db.relationship(
        'AttendanceRecord',
        foreign_keys='AttendanceRecord.modified_by_id',
        back_populates='modified_by',
    )
    enrolled_faces = db.relationship(
        'FaceEnrollment',
        foreign_keys='FaceEnrollment.enrolled_by_id',
        back_populates='enrolled_by',
    )
    audit_logs = db.relationship(
        'AuditLog',
        foreign_keys='AuditLog.user_id',
        back_populates='user',
    )
    updated_settings = db.relationship(
        'SystemSetting',
        foreign_keys='SystemSetting.updated_by_id',
        back_populates='updated_by',
    )

    def set_password(self, password: str) -> None:
        """Hash and store user password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify user password against stored hash."""
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self) -> bool:
        """Return True if user has admin role."""
        return self.role == 'admin'

    @property
    def is_hod(self) -> bool:
        """Return True if user has hod role."""
        return self.role == 'hod'

    @property
    def is_faculty(self) -> bool:
        """Return True if user has faculty role."""
        return self.role == 'faculty'

    @property
    def is_student(self) -> bool:
        """Return True if user has student role."""
        return self.role == 'student'

    def __repr__(self) -> str:
        return f'<User {self.email} ({self.role})>'


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Flask-Login user loader callback."""
    if user_id is not None:
        try:
            return User.query.get(int(user_id))
        except (ValueError, TypeError):
            return None
    return None


class Department(db.Model):
    """Academic department model."""

    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    hod_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # Relationships
    hod = db.relationship(
        'User',
        foreign_keys=[hod_id],
        back_populates='hod_of_department',
    )
    users = db.relationship(
        'User',
        foreign_keys='User.department_id',
        back_populates='department',
    )
    sections = db.relationship(
        'Section',
        back_populates='department',
        cascade='all, delete-orphan',
    )
    students = db.relationship(
        'Student',
        foreign_keys='Student.department_id',
        back_populates='department',
    )
    subjects = db.relationship(
        'Subject',
        back_populates='department',
        cascade='all, delete-orphan',
    )
    classrooms = db.relationship(
        'Classroom',
        back_populates='department',
    )

    def __repr__(self) -> str:
        return f'<Department {self.code} - {self.name}>'


class Section(db.Model):
    """Class section model."""

    __tablename__ = 'sections'
    __table_args__ = (
        db.UniqueConstraint(
            'name',
            'department_id',
            'academic_year',
            'semester',
            name='uq_section_dept_year_sem',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    year = db.Column(db.Integer, nullable=False)
    semester = db.Column(db.Integer, nullable=False)
    academic_year = db.Column(db.String(20), nullable=False)

    # Relationships
    department = db.relationship(
        'Department',
        back_populates='sections',
    )
    students = db.relationship(
        'Student',
        foreign_keys='Student.section_id',
        back_populates='section',
    )
    faculty_mappings = db.relationship(
        'FacultySubjectMapping',
        back_populates='section',
        cascade='all, delete-orphan',
    )
    sessions = db.relationship(
        'AttendanceSession',
        back_populates='section',
    )

    def __repr__(self) -> str:
        return f'<Section {self.name} (Year {self.year}, Sem {self.semester})>'


class Student(db.Model):
    """Student profile linked to a User account."""

    __tablename__ = 'students'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True,
    )
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    admission_number = db.Column(db.String(50), unique=True, nullable=True, index=True)
    section_id = db.Column(
        db.Integer,
        db.ForeignKey('sections.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    year = db.Column(db.Integer, nullable=False)

    # Relationships
    user = db.relationship(
        'User',
        back_populates='student_profile',
    )
    section = db.relationship(
        'Section',
        foreign_keys=[section_id],
        back_populates='students',
    )
    department = db.relationship(
        'Department',
        foreign_keys=[department_id],
        back_populates='students',
    )
    attendance_records = db.relationship(
        'AttendanceRecord',
        back_populates='student',
        cascade='all, delete-orphan',
    )
    face_enrollments = db.relationship(
        'FaceEnrollment',
        back_populates='student',
        cascade='all, delete-orphan',
    )
    face_recognition_logs = db.relationship(
        'FaceRecognitionLog',
        back_populates='student',
    )
    notifications = db.relationship(
        'Notification',
        back_populates='student',
        cascade='all, delete-orphan',
    )

    def __repr__(self) -> str:
        return f'<Student {self.roll_number}>'


class Subject(db.Model):
    """Academic subject / course model."""

    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    credits = db.Column(db.Integer, default=3, nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    semester = db.Column(db.Integer, nullable=False)

    # Relationships
    department = db.relationship(
        'Department',
        back_populates='subjects',
    )
    faculty_mappings = db.relationship(
        'FacultySubjectMapping',
        back_populates='subject',
        cascade='all, delete-orphan',
    )
    sessions = db.relationship(
        'AttendanceSession',
        back_populates='subject',
    )

    def __repr__(self) -> str:
        return f'<Subject {self.code} - {self.name}>'


class Classroom(db.Model):
    """Classroom or laboratory room model."""

    __tablename__ = 'classrooms'

    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    floor = db.Column(db.Integer, default=1, nullable=False)
    capacity = db.Column(db.Integer, default=60, nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # Relationships
    department = db.relationship(
        'Department',
        back_populates='classrooms',
    )
    timetables = db.relationship(
        'Timetable',
        back_populates='classroom',
    )
    sessions = db.relationship(
        'AttendanceSession',
        back_populates='classroom',
    )

    def __repr__(self) -> str:
        return f'<Classroom {self.room_number}>'


class FacultySubjectMapping(db.Model):
    """Mapping of faculty member to subject, section, and academic term."""

    __tablename__ = 'faculty_subject_mappings'
    __table_args__ = (
        db.UniqueConstraint(
            'faculty_id',
            'subject_id',
            'section_id',
            'academic_year',
            'semester',
            name='uq_faculty_subject_section_ay_sem',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    faculty_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    subject_id = db.Column(
        db.Integer,
        db.ForeignKey('subjects.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    section_id = db.Column(
        db.Integer,
        db.ForeignKey('sections.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    academic_year = db.Column(db.String(20), nullable=False)
    semester = db.Column(db.Integer, nullable=False)

    # Relationships
    faculty = db.relationship(
        'User',
        foreign_keys=[faculty_id],
        back_populates='faculty_mappings',
    )
    subject = db.relationship(
        'Subject',
        foreign_keys=[subject_id],
        back_populates='faculty_mappings',
    )
    section = db.relationship(
        'Section',
        foreign_keys=[section_id],
        back_populates='faculty_mappings',
    )
    timetables = db.relationship(
        'Timetable',
        back_populates='mapping',
        cascade='all, delete-orphan',
    )

    def __repr__(self) -> str:
        return (
            f'<FacultySubjectMapping Faculty:{self.faculty_id} '
            f'Subject:{self.subject_id} Section:{self.section_id}>'
        )


class Timetable(db.Model):
    """Timetable schedule slot for a course section."""

    __tablename__ = 'timetables'

    id = db.Column(db.Integer, primary_key=True)
    faculty_subject_mapping_id = db.Column(
        db.Integer,
        db.ForeignKey('faculty_subject_mappings.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    classroom_id = db.Column(
        db.Integer,
        db.ForeignKey('classrooms.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    day_of_week = db.Column(db.Integer, nullable=False, index=True)  # 0=Monday, 6=Sunday
    period_number = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    mapping = db.relationship(
        'FacultySubjectMapping',
        back_populates='timetables',
    )
    classroom = db.relationship(
        'Classroom',
        back_populates='timetables',
    )
    sessions = db.relationship(
        'AttendanceSession',
        back_populates='timetable',
    )

    def __repr__(self) -> str:
        return (
            f'<Timetable Day:{self.day_of_week} '
            f'Period:{self.period_number} ({self.start_time}-{self.end_time})>'
        )


class AttendanceSession(db.Model):
    """An attendance tracking session for a scheduled or impromptu class."""

    __tablename__ = 'attendance_sessions'

    id = db.Column(db.Integer, primary_key=True)
    timetable_id = db.Column(
        db.Integer,
        db.ForeignKey('timetables.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    faculty_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    subject_id = db.Column(
        db.Integer,
        db.ForeignKey('subjects.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    section_id = db.Column(
        db.Integer,
        db.ForeignKey('sections.id', ondelete='RESTRICT'),
        nullable=False,
        index=True,
    )
    classroom_id = db.Column(
        db.Integer,
        db.ForeignKey('classrooms.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    date = db.Column(db.Date, nullable=False, index=True)
    period_number = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.DateTime(timezone=True), nullable=True)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    scheduled_duration_minutes = db.Column(db.Integer, default=50, nullable=False)
    status = db.Column(
        db.String(20),
        default='started',
        nullable=False,
        index=True,
    )  # started, in_progress, paused, completed, cancelled
    camera_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    timetable = db.relationship(
        'Timetable',
        back_populates='sessions',
    )
    faculty = db.relationship(
        'User',
        foreign_keys=[faculty_id],
        back_populates='sessions_conducted',
    )
    subject = db.relationship(
        'Subject',
        foreign_keys=[subject_id],
        back_populates='sessions',
    )
    section = db.relationship(
        'Section',
        foreign_keys=[section_id],
        back_populates='sessions',
    )
    classroom = db.relationship(
        'Classroom',
        foreign_keys=[classroom_id],
        back_populates='sessions',
    )
    records = db.relationship(
        'AttendanceRecord',
        back_populates='session',
        cascade='all, delete-orphan',
    )
    recognition_logs = db.relationship(
        'FaceRecognitionLog',
        back_populates='session',
        cascade='all, delete-orphan',
    )

    def __repr__(self) -> str:
        return f'<AttendanceSession id={self.id} date={self.date} status={self.status}>'


class AttendanceRecord(db.Model):
    """Attendance summary record for a specific student in a session."""

    __tablename__ = 'attendance_records'
    __table_args__ = (
        db.UniqueConstraint('session_id', 'student_id', name='uq_session_student_record'),
    )

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey('attendance_sessions.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('students.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.String(20),
        default='absent',
        nullable=False,
        index=True,
    )  # present, absent, late, needs_review, excused
    first_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    total_observed_seconds = db.Column(db.Float, default=0.0, nullable=False)
    coverage_percentage = db.Column(db.Float, default=0.0, nullable=False)
    confidence_score = db.Column(db.Float, default=0.0, nullable=False)
    is_manually_modified = db.Column(db.Boolean, default=False, nullable=False)
    modified_by_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    modification_reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    session = db.relationship(
        'AttendanceSession',
        back_populates='records',
    )
    student = db.relationship(
        'Student',
        back_populates='attendance_records',
    )
    modified_by = db.relationship(
        'User',
        foreign_keys=[modified_by_id],
        back_populates='modified_records',
    )
    observation_intervals = db.relationship(
        'ObservationInterval',
        back_populates='record',
        cascade='all, delete-orphan',
    )

    def __repr__(self) -> str:
        return (
            f'<AttendanceRecord session={self.session_id} '
            f'student={self.student_id} status={self.status}>'
        )


class ObservationInterval(db.Model):
    """Continuous observation window where a student was detected."""

    __tablename__ = 'observation_intervals'

    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(
        db.Integer,
        db.ForeignKey('attendance_records.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    start_time = db.Column(db.DateTime(timezone=True), nullable=False)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    record = db.relationship(
        'AttendanceRecord',
        back_populates='observation_intervals',
    )

    def __repr__(self) -> str:
        return f'<ObservationInterval record_id={self.record_id} start={self.start_time}>'


class FaceEnrollment(db.Model):
    """Facial feature enrollment metadata linking students to the database embeddings."""

    __tablename__ = 'face_enrollments'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('students.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    embedding_index = db.Column(db.Integer, nullable=False)
    enrolled_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    enrolled_by_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # Relationships
    student = db.relationship(
        'Student',
        back_populates='face_enrollments',
    )
    enrolled_by = db.relationship(
        'User',
        foreign_keys=[enrolled_by_id],
        back_populates='enrolled_faces',
    )

    def __repr__(self) -> str:
        return f'<FaceEnrollment student_id={self.student_id} idx={self.embedding_index}>'


class FaceRecognitionLog(db.Model):
    """Raw inference log from face recognition during an attendance session."""

    __tablename__ = 'face_recognition_logs'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey('attendance_sessions.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('students.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    confidence_score = db.Column(db.Float, default=0.0, nullable=False)
    capture_time = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    recognition_status = db.Column(
        db.String(20),
        default='unknown',
        nullable=False,
        index=True,
    )  # recognized, unknown, uncertain, needs_review
    frame_number = db.Column(db.Integer, default=0, nullable=False)

    # Relationships
    session = db.relationship(
        'AttendanceSession',
        back_populates='recognition_logs',
    )
    student = db.relationship(
        'Student',
        foreign_keys=[student_id],
        back_populates='face_recognition_logs',
    )

    def __repr__(self) -> str:
        return (
            f'<FaceRecognitionLog session={self.session_id} '
            f'status={self.recognition_status} conf={self.confidence_score:.2f}>'
        )


class Notification(db.Model):
    """System notification dispatched to a student (e.g. low attendance alert)."""

    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer,
        db.ForeignKey('students.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    type = db.Column(
        db.String(30),
        nullable=False,
        index=True,
    )  # low_attendance, absent_alert, general
    subject = db.Column(db.Text, nullable=False)
    message = db.Column(db.Text, nullable=False)
    email = db.Column(db.String(255), nullable=False)
    sent_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status = db.Column(
        db.String(20),
        default='pending',
        nullable=False,
        index=True,
    )  # pending, sent, failed, not_configured
    error_message = db.Column(db.Text, nullable=True)

    # Relationships
    student = db.relationship(
        'Student',
        back_populates='notifications',
    )

    def __repr__(self) -> str:
        return f'<Notification student_id={self.student_id} type={self.type} status={self.status}>'


class AuditLog(db.Model):
    """Audit trail for security, configuration, and manual attendance overrides."""

    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    reason = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        back_populates='audit_logs',
    )

    def __repr__(self) -> str:
        return f'<AuditLog user_id={self.user_id} action={self.action} entity={self.entity_type}>'


class SystemSetting(db.Model):
    """Application-wide dynamic configuration key-value storage."""

    __tablename__ = 'system_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)
    updated_by_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    updated_by = db.relationship(
        'User',
        foreign_keys=[updated_by_id],
        back_populates='updated_settings',
    )

    def __repr__(self) -> str:
        return f'<SystemSetting key={self.key}>'


class SignupRequest(db.Model):
    """A faculty/admin self-registration waiting for an administrator's approval."""

    __tablename__ = 'signup_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
    )
    requested_role = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f'<SignupRequest user_id={self.user_id} role={self.requested_role}>'


class OtpToken(db.Model):
    """One-time password for e-mail password reset. Only a salted hash of the code is stored."""

    __tablename__ = 'otp_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    salt = db.Column(db.String(32), nullable=False)
    code_hash = db.Column(db.String(64), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f'<OtpToken user_id={self.user_id} used={self.used}>'


class FaceEmbedding(db.Model):
    """One 128-d SFace vector per enrolment photo. The permanent store of every student's face."""

    __tablename__ = 'face_embeddings'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False, index=True
    )
    vector = db.Column(db.LargeBinary(1024), nullable=False)  # float32[128]
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class StudentSubject(db.Model):
    """Subjects a student has actually taken. Attendance in a subject's class is only
    marked for students enrolled in that subject (students with no rows fall back to section-only)."""

    __tablename__ = 'student_subjects'
    __table_args__ = (db.UniqueConstraint('student_id', 'subject_id', name='uq_student_subject'),)

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey('students.id', ondelete='CASCADE'), nullable=False, index=True
    )
    subject_id = db.Column(
        db.Integer, db.ForeignKey('subjects.id', ondelete='CASCADE'), nullable=False, index=True
    )
