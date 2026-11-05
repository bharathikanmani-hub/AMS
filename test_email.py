"""Check your e-mail setup:  python test_email.py you@example.com
Prints the exact reason if Gmail refuses the login or the network blocks SMTP."""
import sys

from app import create_app
from services.email_service import is_smtp_configured, send_email

app = create_app()
with app.app_context():
    if not is_smtp_configured():
        print("MAIL_EMAIL / MAIL_APP_PASSWORD are empty. Put them in .env (see EMAIL_SETUP.md), then restart.")
        sys.exit(1)
    to = sys.argv[1] if len(sys.argv) > 1 else app.config["MAIL_EMAIL"]
    ok, msg = send_email(to, "AttendAI test e-mail", "E-mail is working.")
    print("OK - check the inbox (and Spam) of", to) if ok else print("FAILED:", msg)
