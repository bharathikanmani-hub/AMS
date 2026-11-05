"""Student Blueprint stub for AttendAI.

Provides student-level dashboard and own-data access. Full implementation in Module 2+.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import current_user, login_required
from functools import wraps

student_bp = Blueprint('student', __name__, url_prefix='/student')


def student_required(f):
    """Ensure user is authenticated and has student role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if getattr(current_user, 'role', '') != 'student':
            from flask import abort
            abort(403)
        return f(*args, **kwargs)
    return decorated


@student_bp.route('/dashboard')
@student_required
def dashboard():
    """Student dashboard — stub for Module 1."""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({
            'message': 'Student dashboard',
            'user': current_user.email,
            'role': current_user.role
        })
    try:
        return render_template('student/dashboard.html')
    except Exception:
        return render_template('home.html', user=current_user)
