"""Report generation service for CSV, Excel, and PDF exports."""

import csv
import io
import logging
from datetime import datetime
from typing import List, Optional

from extensions import db
from models import (
    AttendanceRecord, AttendanceSession, Student, Subject,
    Department, Section, User
)

logger = logging.getLogger(__name__)


def get_filtered_records(
    department_id: Optional[int] = None,
    section_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    student_id: Optional[int] = None,
) -> list:
    """Get attendance records with filters applied."""
    query = db.session.query(
        AttendanceRecord,
        Student,
        AttendanceSession,
        Subject
    ).join(
        Student, AttendanceRecord.student_id == Student.id
    ).join(
        AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id
    ).outerjoin(
        Subject, AttendanceSession.subject_id == Subject.id
    )
    
    if department_id:
        query = query.filter(Student.department_id == department_id)
    if section_id:
        query = query.filter(Student.section_id == section_id)
    if subject_id:
        query = query.filter(AttendanceSession.subject_id == subject_id)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(AttendanceSession.date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(AttendanceSession.date <= ed)
        except ValueError:
            pass
    if student_id:
        query = query.filter(AttendanceRecord.student_id == student_id)
    
    return query.order_by(AttendanceSession.date.desc(), Student.roll_number).all()


def generate_csv(records: list) -> str:
    """Generate CSV string from attendance records."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Date', 'Period', 'Subject', 'Student Roll', 'Student Name',
        'Status', 'Coverage %', 'Observed Minutes', 'Confidence'
    ])
    
    for record, student, session, subject in records:
        user = User.query.get(student.user_id)
        writer.writerow([
            session.date.strftime('%Y-%m-%d') if session.date else '',
            session.period_number or '',
            subject.name if subject else '',
            student.roll_number or '',
            user.name if user else '',
            record.status or '',
            f'{record.coverage_percentage:.1f}' if record.coverage_percentage else '0',
            f'{(record.total_observed_seconds or 0) / 60:.1f}',
            f'{record.confidence_score:.3f}' if record.confidence_score else '',
        ])
    
    return output.getvalue()


def generate_excel(records: list) -> bytes:
    """Generate Excel file from attendance records."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        raise RuntimeError('openpyxl is required for Excel export. Install with: pip install openpyxl')
    
    wb = Workbook()
    ws = wb.active
    ws.title = 'Attendance Report'
    
    # Header style
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='4F46E5', end_color='4F46E5', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    headers = [
        'Date', 'Period', 'Subject', 'Student Roll', 'Student Name',
        'Status', 'Coverage %', 'Observed Minutes', 'Confidence'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border
    
    # Status colors
    status_fills = {
        'present': PatternFill(start_color='D4EDDA', end_color='D4EDDA', fill_type='solid'),
        'absent': PatternFill(start_color='F8D7DA', end_color='F8D7DA', fill_type='solid'),
        'late': PatternFill(start_color='FFF3CD', end_color='FFF3CD', fill_type='solid'),
        'needs_review': PatternFill(start_color='D1ECF1', end_color='D1ECF1', fill_type='solid'),
        'excused': PatternFill(start_color='E2E3E5', end_color='E2E3E5', fill_type='solid'),
    }
    
    for row_idx, (record, student, session, subject) in enumerate(records, 2):
        user = User.query.get(student.user_id)
        data = [
            session.date.strftime('%Y-%m-%d') if session.date else '',
            session.period_number or '',
            subject.name if subject else '',
            student.roll_number or '',
            user.name if user else '',
            (record.status or '').title(),
            round(record.coverage_percentage or 0, 1),
            round((record.total_observed_seconds or 0) / 60, 1),
            round(record.confidence_score or 0, 3),
        ]
        
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.border = thin_border
            if col == 6:  # Status column
                fill = status_fills.get(record.status, None)
                if fill:
                    cell.fill = fill
    
    # Auto-width columns
    for col in ws.columns:
        max_length = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_length + 3, 30)
    
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def generate_pdf(records: list, title: str = 'Attendance Report') -> bytes:
    """Generate PDF report from attendance records."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except ImportError:
        raise RuntimeError('reportlab is required for PDF export. Install with: pip install reportlab')
    
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), topMargin=0.5*inch)
    styles = getSampleStyleSheet()
    elements = []
    
    # Title
    elements.append(Paragraph(title, styles['Title']))
    elements.append(Paragraph(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Table data
    data = [['Date', 'Period', 'Subject', 'Roll No', 'Name', 'Status', 'Coverage%', 'Obs Min']]
    
    for record, student, session, subject in records:
        user = User.query.get(student.user_id)
        data.append([
            session.date.strftime('%Y-%m-%d') if session.date else '',
            str(session.period_number or ''),
            (subject.name if subject else '')[:20],
            student.roll_number or '',
            (user.name if user else '')[:20],
            (record.status or '').title(),
            f'{record.coverage_percentage or 0:.1f}',
            f'{(record.total_observed_seconds or 0) / 60:.1f}',
        ])
    
    if len(data) > 1:
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F7F8FC')]),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph('No records found.', styles['Normal']))
    
    doc.build(elements)
    return output.getvalue()
