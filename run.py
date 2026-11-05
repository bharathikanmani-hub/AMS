"""Development entry point for AttendAI."""

from app import app

if __name__ == '__main__':
    print('=' * 50)
    print('  AttendAI — AI Classroom Attendance System')
    print('  Running at http://127.0.0.1:5000')
    print('=' * 50)
    app.run(host='127.0.0.1', port=5000, debug=True)
