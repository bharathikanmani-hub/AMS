"""Email notification service."""

import smtplib
import logging
from email.message import EmailMessage
from typing import Tuple

from flask import current_app
from extensions import db
from models import Notification

logger = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    """Check if SMTP credentials are configured."""
    email = current_app.config.get('MAIL_EMAIL', '')
    password = current_app.config.get('MAIL_APP_PASSWORD', '')
    return bool(email and password)


def send_email(to_email: str, subject: str, body: str) -> Tuple[bool, str]:
    """Send an email via SMTP.
    
    Returns (success, message).
    """
    if not is_smtp_configured():
        return False, 'SMTP not configured. Set MAIL_EMAIL and MAIL_APP_PASSWORD in .env'
    
    mail_email = current_app.config['MAIL_EMAIL']
    mail_password = current_app.config['MAIL_APP_PASSWORD']
    smtp_host = current_app.config.get('MAIL_SMTP_HOST', 'smtp.gmail.com')
    smtp_port = current_app.config.get('MAIL_SMTP_PORT', 587)
    
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = mail_email
    msg['To'] = to_email
    msg.set_content(body)
    
    mail_password = "".join(str(mail_password).split())          # Gmail shows app passwords with spaces
    attempts = [(smtp_host, int(smtp_port), "tls")]
    if int(smtp_port) != 465:
        attempts.append((smtp_host, 465, "ssl"))                  # many networks block 587 but allow 465
    last = ""
    for host, port, mode in attempts:
        try:
            if mode == "ssl":
                server = smtplib.SMTP_SSL(host, port, timeout=15)
            else:
                server = smtplib.SMTP(host, port, timeout=15)
                server.ehlo()
                server.starttls()
                server.ehlo()
            with server:
                server.login(mail_email, mail_password)
                server.send_message(msg)
            logger.info('Email sent to %s: %s', to_email, subject)
            return True, 'Email sent successfully'
        except smtplib.SMTPAuthenticationError:
            last = 'Gmail rejected the login. Use a 16-letter App Password (2-Step Verification must be ON), not your normal password.'
            break
        except Exception as e:
            last = f'{type(e).__name__}: {e}'
            logger.error('SMTP %s:%s failed: %s', host, port, e)
    logger.error('Failed to send email to %s: %s', to_email, last)
    return False, f'Email send failed: {last}'


def send_low_attendance_alert(
    student_id: int,
    student_email: str,
    student_name: str,
    attendance_percentage: float,
    threshold: float
) -> Tuple[bool, str]:
    """Send low attendance alert to student and log it."""
    # Check for duplicate recent notification
    from datetime import datetime, timedelta, timezone
    recent = Notification.query.filter_by(
        student_id=student_id,
        type='low_attendance'
    ).filter(
        Notification.sent_at >= datetime.now(timezone.utc) - timedelta(days=7)
    ).first()
    
    if recent:
        return False, 'Alert already sent within the last 7 days'
    
    subject = f'Low Attendance Warning - AttendAI'
    body = (
        f'Dear {student_name},\n\n'
        f'Your current attendance is {attendance_percentage:.1f}%, '
        f'which is below the required threshold of {threshold:.0f}%.\n\n'
        f'Please ensure regular attendance to avoid academic consequences.\n\n'
        f'Regards,\nAttendAI System'
    )
    
    notification = Notification(
        student_id=student_id,
        type='low_attendance',
        subject=subject,
        message=body,
        email=student_email,
        status='pending'
    )
    db.session.add(notification)
    
    if is_smtp_configured():
        success, msg = send_email(student_email, subject, body)
        notification.status = 'sent' if success else 'failed'
        if not success:
            notification.error_message = msg
        from datetime import datetime, timezone
        notification.sent_at = datetime.now(timezone.utc)
    else:
        notification.status = 'not_configured'
        notification.error_message = 'SMTP not configured'
        msg = 'SMTP not configured - notification logged but not sent'
        success = False
    
    db.session.commit()
    return success, msg
