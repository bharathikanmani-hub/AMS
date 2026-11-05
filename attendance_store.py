"""Read and write attendance.csv with a single consistent format."""

import csv
import os
from datetime import datetime

from config import ATTENDANCE_FILE, ATTENDANCE_HEADER, DATASET_FOLDER


def ensure_attendance_file():
    if os.path.exists(ATTENDANCE_FILE):
        return
    with open(ATTENDANCE_FILE, "w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerow(ATTENDANCE_HEADER)


def registered_students():
    if not os.path.isdir(DATASET_FOLDER):
        return []
    students = [
        name
        for name in os.listdir(DATASET_FOLDER)
        if os.path.isdir(os.path.join(DATASET_FOLDER, name))
    ]
    students.sort()
    return students


def _parse_row(row):
    if not row:
        return None

    first = row[0].strip()
    if first.lower() in {"date", "time"}:
        return None

    if len(row) < 4:
        return None

    date, second, third, fourth = [item.strip() for item in row[:4]]

    if third.lower() in {"present", "absent"}:
        return {
            "date": date,
            "student_id": second,
            "status": third.title(),
            "time": fourth,
        }

    if fourth.lower() in {"present", "absent"}:
        return {
            "date": date,
            "student_id": third,
            "status": fourth.title(),
            "time": second,
        }

    return None


def read_records():
    ensure_attendance_file()
    records = []
    with open(ATTENDANCE_FILE, newline="", encoding="utf-8") as file:
        for row in csv.reader(file):
            parsed = _parse_row(row)
            if parsed:
                records.append(parsed)
    return records


def append_record(student_id, status, day=None, time_str=None):
    ensure_attendance_file()
    now = datetime.now()
    with open(ATTENDANCE_FILE, "a", newline="", encoding="utf-8") as file:
        csv.writer(file).writerow(
            [
                day or now.strftime("%Y-%m-%d"),
                student_id,
                status,
                time_str or now.strftime("%H:%M:%S"),
            ]
        )


def records_for_date(day):
    return [row for row in read_records() if row["date"] == day]


def student_marked_today(student_id, day):
    return any(
        row["student_id"] == student_id and row["status"] == "Present"
        for row in records_for_date(day)
    )


def student_history(student_id):
    return [row for row in read_records() if row["student_id"] == str(student_id)]


def summarize(day=None):
    students = registered_students()
    day = day or datetime.now().strftime("%Y-%m-%d")
    today_rows = records_for_date(day)

    present_ids = sorted(
        {row["student_id"] for row in today_rows if row["status"] == "Present"}
    )
    absent_ids = sorted(
        {row["student_id"] for row in today_rows if row["status"] == "Absent"}
    )

    if students:
        absent_ids = [student for student in students if student not in present_ids]

    total = len(students) or len(set(row["student_id"] for row in today_rows))
    present_count = len(present_ids)
    absent_count = max(total - present_count, 0)
    percent = round((present_count / total) * 100) if total else 0

    records = read_records()
    unique_ids = sorted({row["student_id"] for row in records} | set(students))
    student_stats = []
    for student_id in unique_ids:
        history = student_history(student_id)
        days = {}
        for row in history:
            days.setdefault(row["date"], row["status"])
            if row["status"] == "Present":
                days[row["date"]] = "Present"
        total_days = len(days)
        present_days = sum(1 for status in days.values() if status == "Present")
        attendance_percent = (
            round((present_days / total_days) * 100) if total_days else 0
        )
        student_stats.append(
            {
                "id": student_id,
                "presentDays": present_days,
                "totalDays": total_days,
                "attendance": attendance_percent,
            }
        )

    return {
        "date": day,
        "totalStudents": total,
        "present": present_count,
        "absent": absent_count,
        "percentage": percent,
        "presentIds": present_ids,
        "absentIds": absent_ids,
        "today": today_rows,
        "students": student_stats,
        "records": records,
    }
