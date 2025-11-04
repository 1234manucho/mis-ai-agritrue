# make_admin.py
import os
import sys
from werkzeug.security import generate_password_hash

# --- adjust imports to match your app structure ---
# This assumes your app factory create_app() is importable from app.py (or adjust accordingly)
try:
    from app import create_app
except Exception as e:
    print("Error importing create_app from app.py:", e)
    sys.exit(1)

# Import DB and models after app context is available
from extensions import db
from models import User  # adjust path if models import path differs

# Firebase
import firebase_admin
from firebase_admin import credentials, auth

# === CONFIG ===
SERVICE_ACCOUNT_PATH = "serviceAccountKey.json"  # path to your service account JSON
EMAIL = "info@agritrue.org"
PASSWORD = "agritrue@30"
FULLNAME = "Chills Emmanuel"  # change as desired
USERNAME = "chills"

# === Initialize Flask app and Firebase, then run ===
app = create_app()

with app.app_context():
    # Initialize Firebase Admin SDK if not already
    if not firebase_admin._apps:
        if not os.path.exists(SERVICE_ACCOUNT_PATH):
            print(f"Service account file not found at: {SERVICE_ACCOUNT_PATH}")
            sys.exit(1)
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized.")

    # 1) Create or fetch firebase user
    fb_user = None
    try:
        fb_user = auth.get_user_by_email(EMAIL)
        print(f"Found existing Firebase user: uid={fb_user.uid}")
    except firebase_admin._auth_utils.UserNotFoundError:
        print("No Firebase user found — creating new user...")
        fb_user = auth.create_user(
            email=EMAIL,
            email_verified=True,
            password=PASSWORD,
            display_name=FULLNAME,
        )
        print(f"Created Firebase user uid={fb_user.uid}")

    # 2) Set custom claim admin = True
    try:
        auth.set_custom_user_claims(fb_user.uid, {'admin': True})
        print("Set custom claim: admin = True")
    except Exception as e:
        print("Failed to set custom claim:", e)

    # 3) Ensure local DB has this user and set is_admin
    # Note: adjust the User model field names to match your app's User model fields
    existing = db.session.get(User, fb_user.uid)
    if existing:
        print("Local user record already exists. Updating is_admin and other fields...")
        existing.is_admin = True
        existing.email = EMAIL
        existing.fullname = FULLNAME
        existing.username = USERNAME
        # store hashed password for local login if you use local auth
        existing.password = generate_password_hash(PASSWORD)
        existing.last_login = existing.last_login  # keep existing
        db.session.commit()
        print("Local user updated and granted admin.")
    else:
        print("Creating local DB user record...")
        new_user = User(
            id=fb_user.uid,
            fullname=FULLNAME,
            username=USERNAME,
            email=EMAIL,
            phone=None,
            country=None,
            county=None,
            is_admin=True,
            password=generate_password_hash(PASSWORD)
        )
        db.session.add(new_user)
        db.session.commit()
        print("Local user created and granted admin.")

    print("✅ Done. Admin user created/updated. You can now login using the normal login page.")
