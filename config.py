"""Application configuration loaded from environment variables."""

import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    """Base configuration. Secrets and database credentials come from .env."""

    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-in-production')

    # Database — MySQL only (no SQLite fallback)
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_NAME = os.getenv('DB_NAME', 'classroom_attendance')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = quote_plus(os.getenv('DB_PASSWORD', ''))
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        "?charset=utf8mb4"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 300,
        'pool_pre_ping': True,
    }

    # Session
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour

    # CSRF
    WTF_CSRF_ENABLED = True

    # Email
    MAIL_EMAIL = os.getenv("MAIL_EMAIL", "").strip()
    MAIL_APP_PASSWORD = os.getenv('MAIL_APP_PASSWORD', '').replace(' ', '')  # Gmail shows app passwords with spaces
    MAIL_SMTP_HOST = os.getenv('MAIL_SMTP_HOST', 'smtp.gmail.com')
    MAIL_SMTP_PORT = int(os.getenv('MAIL_SMTP_PORT', '587'))
    # When SMTP is not set up, print password-reset codes in the server window (development only)
    MAIL_DEV_PRINT_OTP = os.getenv('MAIL_DEV_PRINT_OTP', 'true').lower() == 'true'

    # true = Live Attendance can only be started inside a scheduled timetable period (+/- 10 min)
    ENFORCE_TIMETABLE = os.getenv('ENFORCE_TIMETABLE', 'false').lower() == 'true'

    # Attendance rules
    ATTENDANCE_COVERAGE_THRESHOLD = float(os.getenv('ATTENDANCE_COVERAGE_THRESHOLD', '0.70'))
    LOW_ATTENDANCE_THRESHOLD = float(os.getenv('LOW_ATTENDANCE_THRESHOLD', '75'))

    # Every period is 45 minutes; a student with less than 20 minutes in class is absent
    PERIOD_MINUTES = 45
    MIN_PRESENT_MINUTES = 20

    # Face recognition (existing OpenCV YuNet / SFace models)
    YUNET_MODEL = os.path.join(BASE_DIR, 'face_detection_yunet_2026may.onnx')
    SFACE_MODEL = os.path.join(BASE_DIR, 'face_recognition_sface_2021dec.onnx')
    DATASET_FOLDER = os.path.join(BASE_DIR, 'dataset')
    DATABASE_FILE = os.path.join(BASE_DIR, 'face_database.npz')
    RECOGNITION_THRESHOLD = float(os.getenv('RECOGNITION_THRESHOLD', '0.38'))
    PHOTOS_PER_STUDENT = int(os.getenv('PHOTOS_PER_STUDENT', '15'))
    CAPTURE_DELAY_SECONDS = float(os.getenv('CAPTURE_DELAY_SECONDS', '1.0'))

    # Legacy compatibility paths
    ATTENDANCE_FILE = os.path.join(BASE_DIR, 'attendance.csv')
    USERS_FILE = os.path.join(BASE_DIR, 'users.json')
    ATTENDANCE_HEADER = ['Date', 'Student ID', 'Status', 'Time']

    # Built React frontend (npm run build -> copy dist/ here as frontend_dist/)
    FRONTEND_DIST = os.path.join(BASE_DIR, 'frontend_dist')

    # Upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB


class TestConfig(Config):
    """Test configuration using SQLite in-memory."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret-key'


# Module-level exports for backward compatibility with OpenCV scripts
YUNET_MODEL = Config.YUNET_MODEL
SFACE_MODEL = Config.SFACE_MODEL
DATASET_FOLDER = Config.DATASET_FOLDER
DATABASE_FILE = Config.DATABASE_FILE
RECOGNITION_THRESHOLD = Config.RECOGNITION_THRESHOLD
PHOTOS_PER_STUDENT = Config.PHOTOS_PER_STUDENT
CAPTURE_DELAY_SECONDS = Config.CAPTURE_DELAY_SECONDS
ATTENDANCE_FILE = Config.ATTENDANCE_FILE
USERS_FILE = Config.USERS_FILE
ATTENDANCE_HEADER = Config.ATTENDANCE_HEADER
