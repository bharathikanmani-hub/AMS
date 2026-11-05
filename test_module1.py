"""Module 1 verification tests for AttendAI.

Tests: app factory, model imports, db connection, auth routes, role-based access.
Run with: python test_module1.py
"""

import sys
import os

# Ensure the Classroom directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def test_app_factory():
    """Test 1: Flask application factory creates app correctly."""
    separator("TEST 1: Application Factory")
    try:
        from app import create_app
        app = create_app()
        assert app is not None, "App should not be None"
        assert app.config['SQLALCHEMY_DATABASE_URI'], "Database URI should be set"
        print(f"  [PASS] App created successfully")
        print(f"  [INFO] DB URI: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
        return app
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        return None

def test_model_imports():
    """Test 2: All required models can be imported."""
    separator("TEST 2: Model Imports")
    try:
        from models import (
            User, Department, Section, Student, Subject,
            Classroom, FacultySubjectMapping, Timetable,
            AttendanceSession, AttendanceRecord,
            FaceEnrollment, FaceRecognitionLog,
            Notification, AuditLog, SystemSetting,
        )
        models = [
            User, Department, Section, Student, Subject,
            Classroom, FacultySubjectMapping, Timetable,
            AttendanceSession, AttendanceRecord,
        ]
        for m in models:
            print(f"  [PASS] {m.__name__} -> table '{m.__tablename__}'")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        return False

def test_db_connection(app):
    """Test 3: Database connection works."""
    separator("TEST 3: Database Connection")
    if app is None:
        print("  [SKIP] No app available")
        return False
    try:
        with app.app_context():
            from extensions import db
            from sqlalchemy import text
            result = db.session.execute(text('SELECT 1')).scalar()
            assert result == 1, "SELECT 1 should return 1"
            print(f"  [PASS] MySQL connection successful (SELECT 1 = {result})")

            # Check database name
            db_name = db.session.execute(text('SELECT DATABASE()')).scalar()
            print(f"  [PASS] Connected to database: {db_name}")
            return True
    except Exception as e:
        print(f"  [FAIL] Database connection error: {e}")
        print(f"  [INFO] Make sure MySQL is running and .env has correct credentials")
        return False

def test_health_endpoint(app):
    """Test 4: Health check endpoint."""
    separator("TEST 4: Health Check Endpoint")
    if app is None:
        print("  [SKIP] No app available")
        return False
    try:
        with app.test_client() as client:
            resp = client.get('/health')
            data = resp.get_json()
            print(f"  [INFO] Status: {resp.status_code}, Body: {data}")
            if resp.status_code == 200:
                print(f"  [PASS] Health check passed")
                return True
            else:
                print(f"  [WARN] Health check returned {resp.status_code} — DB may be unreachable")
                return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False

def test_login_page(app):
    """Test 5: Login page renders correctly."""
    separator("TEST 5: Login Page")
    if app is None:
        print("  [SKIP] No app available")
        return False
    try:
        with app.test_client() as client:
            resp = client.get('/auth/login')
            print(f"  [INFO] Status: {resp.status_code}")
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
            html = resp.data.decode('utf-8')
            assert 'login' in html.lower() or 'sign in' in html.lower() or 'email' in html.lower(), \
                "Page should contain login-related content"
            print(f"  [PASS] Login page renders (HTTP 200, contains login form)")
            return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        return False

def test_protected_routes(app):
    """Test 6: Protected routes redirect unauthenticated users."""
    separator("TEST 6: Protected Route Redirect")
    if app is None:
        print("  [SKIP] No app available")
        return False
    try:
        with app.test_client() as client:
            routes_to_test = ['/home', '/admin/dashboard', '/hod/dashboard']
            all_pass = True
            for route in routes_to_test:
                resp = client.get(route, follow_redirects=False)
                if resp.status_code in (302, 301, 308):
                    print(f"  [PASS] {route} -> redirects (HTTP {resp.status_code})")
                elif resp.status_code == 403:
                    print(f"  [PASS] {route} -> forbidden for anon (HTTP 403)")
                else:
                    print(f"  [WARN] {route} -> HTTP {resp.status_code}")
                    all_pass = False
            return all_pass
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False

def test_login_flow(app):
    """Test 7: Login with invalid credentials returns 401."""
    separator("TEST 7: Login Flow (Invalid Credentials)")
    if app is None:
        print("  [SKIP] No app available")
        return False
    try:
        with app.test_client() as client:
            resp = client.post('/auth/login',
                json={'email': 'nonexistent@test.com', 'password': 'wrong'},
                content_type='application/json')
            print(f"  [INFO] Status: {resp.status_code}")
            assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
            print(f"  [PASS] Invalid login correctly returns HTTP 401")
            return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback; traceback.print_exc()
        return False

def test_logout_redirect(app):
    """Test 8: Logout redirects unauthenticated user."""
    separator("TEST 8: Logout Redirect")
    if app is None:
        print("  [SKIP] No app available")
        return False
    try:
        with app.test_client() as client:
            resp = client.get('/auth/logout', follow_redirects=False)
            if resp.status_code in (302, 301, 308):
                print(f"  [PASS] /auth/logout redirects unauthenticated user (HTTP {resp.status_code})")
                return True
            else:
                print(f"  [WARN] /auth/logout returned HTTP {resp.status_code}")
                return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  AttendAI Module 1 — Verification Tests")
    print("=" * 60)

    results = {}

    app = test_app_factory()
    results['App Factory'] = app is not None

    results['Model Imports'] = test_model_imports()
    results['DB Connection'] = test_db_connection(app)
    results['Health Endpoint'] = test_health_endpoint(app)
    results['Login Page'] = test_login_page(app)
    results['Protected Routes'] = test_protected_routes(app)
    results['Login Flow'] = test_login_flow(app)
    results['Logout Redirect'] = test_logout_redirect(app)

    separator("RESULTS SUMMARY")
    passed = 0
    failed = 0
    for name, result in results.items():
        status = "PASS" if result else "FAIL"
        icon = "✓" if result else "✗"
        if result:
            passed += 1
        else:
            failed += 1
        print(f"  {icon} {name}: {status}")

    print(f"\n  Total: {passed} passed, {failed} failed out of {len(results)}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
