"""Faculty Blueprint stub for AttendAI.

Provides faculty-level dashboard access. Full implementation in Module 2+.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import current_user, login_required
from functools import wraps

faculty_bp = Blueprint('faculty', __name__, url_prefix='/faculty')


def faculty_required(f):
    """Ensure user is authenticated and has faculty or hod role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        role = getattr(current_user, 'role', '')
        if role not in ('faculty', 'hod'):
            from flask import abort
            abort(403)
        return f(*args, **kwargs)
    return decorated


@faculty_bp.route('/dashboard')
@faculty_required
def dashboard():
    """Faculty dashboard — stub for Module 1."""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({
            'message': 'Faculty dashboard',
            'user': current_user.email,
            'role': current_user.role
        })
    try:
        return render_template('faculty/dashboard.html')
    except Exception:
        return render_template('home.html', user=current_user)
