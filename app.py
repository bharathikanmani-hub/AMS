"""AttendAI — Flask Application Factory."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required

from config import Config
from extensions import db, login_manager, csrf, migrate


def create_app(config_class=Config):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    # Import models so they are registered with SQLAlchemy
    with app.app_context():
        import models  # noqa: F401

    @login_manager.unauthorized_handler
    def _unauthorized():
        if request.path.startswith('/api/') or _wants_json():
            return jsonify({'ok': False, 'message': 'Please sign in.'}), 401
        flash('Please log in to access this page.', 'warning')
        return redirect(url_for('auth.login', next=request.url))

    # Register blueprints
    _register_blueprints(app)

    _register_spa_assets(app)

    # Register error handlers
    _register_error_handlers(app)

    # Root routes
    @app.route('/')
    def index():
        """Redirect to login or dashboard based on authentication status."""
        spa = _spa_index(app)
        if spa is not None:  # built React frontend present -> serve it
            return spa
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        return redirect(url_for('auth.login'))

    @app.route('/home')
    @login_required
    def home():
        """Protected home page — redirects to role-specific dashboard."""
        role = getattr(current_user, 'role', '').lower()
        if role == 'admin':
            return redirect(url_for('admin.dashboard'))
        elif role == 'hod':
            return redirect(url_for('hod.dashboard'))
        elif role == 'faculty':
            return redirect(url_for('faculty.dashboard'))
        elif role == 'student':
            return redirect(url_for('student.dashboard'))
        return render_template('home.html', user=current_user)

    @app.route('/health')
    def health_check():
        """Database connection health check endpoint."""
        from flask import jsonify
        try:
            from sqlalchemy import text
            db.session.execute(text('SELECT 1'))
            return jsonify({
                'status': 'healthy',
                'database': 'connected',
                'message': 'AttendAI is running.'
            })
        except Exception as e:
            return jsonify({
                'status': 'unhealthy',
                'database': 'disconnected',
                'error': str(e)
            }), 500

    return app


def _register_blueprints(app):
    """Register application blueprints."""
    from routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from routes.api_auth import api_auth_bp
    app.register_blueprint(api_auth_bp)

    from routes.api_live import api_live_bp
    app.register_blueprint(api_live_bp)

    from routes.api_enroll import api_enroll_bp
    app.register_blueprint(api_enroll_bp)

    from routes.api_admin import api_admin_bp
    app.register_blueprint(api_admin_bp)

    from routes.api_dashboard import api_dashboard_bp
    app.register_blueprint(api_dashboard_bp)

    from routes.admin import admin_bp
    app.register_blueprint(admin_bp)  # already has url_prefix='/admin'

    from routes.hod import hod_bp
    app.register_blueprint(hod_bp)  # already has url_prefix='/hod'

    # Faculty and Student blueprints — create stubs if they don't exist yet
    try:
        from routes.faculty import faculty_bp
        app.register_blueprint(faculty_bp)
    except ImportError:
        pass

    try:
        from routes.student import student_bp
        app.register_blueprint(student_bp)
    except ImportError:
        pass


def _register_error_handlers(app):
    """Register HTTP error handlers."""
    @app.errorhandler(400)
    def bad_request(e):
        if _wants_json():
            from flask import jsonify
            return jsonify({'error': 'Bad Request', 'message': str(e)}), 400
        return render_template('errors/400.html'), 400

    @app.errorhandler(403)
    def forbidden(e):
        if _wants_json():
            from flask import jsonify
            return jsonify({'error': 'Forbidden', 'message': 'Access denied.'}), 403
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        if request.method == 'GET' and not request.path.startswith(('/api/', '/auth/', '/admin', '/hod')):
            spa = _spa_index(app)
            if spa is not None:
                return spa
        if _wants_json():
            from flask import jsonify
            return jsonify({'error': 'Not Found', 'message': 'Resource not found.'}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        if _wants_json():
            from flask import jsonify
            return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred.'}), 500
        return render_template('errors/500.html'), 500


def _spa_index(app):
    """Return the built React index.html (frontend_dist/) or None if not built."""
    dist = app.config.get('FRONTEND_DIST')
    if dist and os.path.isfile(os.path.join(dist, 'index.html')):
        return send_from_directory(dist, 'index.html')
    return None


def _register_spa_assets(app):
    """Serve built JS/CSS/images from frontend_dist/assets at /assets/..."""
    dist = app.config.get('FRONTEND_DIST')
    if not dist or not os.path.isdir(os.path.join(dist, 'assets')):
        return

    @app.route('/assets/<path:filename>')
    def spa_assets(filename):
        return send_from_directory(os.path.join(dist, 'assets'), filename)


def _wants_json():
    """Check if the client prefers a JSON response."""
    from flask import request
    return (
        request.is_json
        or request.headers.get('Accept', '') == 'application/json'
    )


# Application entry point
app = create_app()

if __name__ == '__main__':
    print('AttendAI running at http://127.0.0.1:5000')
    app.run(host='127.0.0.1', port=5000, debug=True)
