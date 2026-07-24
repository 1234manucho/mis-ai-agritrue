"""
AgriTrue Flask application.

Production notes:
- Configure DATABASE_URL in Render. Do not hard-code database credentials.
- Run `flask --app app init-db` once after attaching a new database.
- The analyzer endpoints are registered from analyzer_routes.py.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any
from agri_analyzer import AnalyzerError, generate_farming_chat_reply
from analyzer_routes import analyzer_bp
import firebase_admin
import requests
import speech_recognition as sr
from dotenv import load_dotenv
from firebase_admin import auth, credentials, firestore
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_cors import CORS
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import desc, or_, text
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from agri_analyzer import AnalyzerError, generate_farming_chat_reply
from analyzer_routes import analyzer_bp
from extensions import db, migrate
from models import Comment, CommunityNote, DiagnosticResult, User


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
AVATAR_FOLDER = BASE_DIR / "static" / "avatars"

ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

firestore_db = None


def utcnow() -> datetime:
    """Return naive UTC for compatibility with existing SQLAlchemy columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_database_url(value: str | None) -> str:
    """Normalize provider URLs for SQLAlchemy 2.x."""
    database_url = (value or "").strip()

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return database_url or f"sqlite:///{BASE_DIR / 'agritrue.db'}"


def model_columns(model: type[db.Model]) -> set[str]:
    return {column.name for column in model.__table__.columns}


def filtered_model_data(model: type[db.Model], values: dict[str, Any]) -> dict[str, Any]:
    """Only pass fields that really exist on the current model."""
    allowed = model_columns(model)
    return {
        key: value
        for key, value in values.items()
        if key in allowed and value is not None
    }


def model_primary_key_value(model: type[db.Model], raw_value: Any) -> Any:
    """Convert route/login IDs to the model's primary-key Python type."""
    try:
        column = model.__mapper__.primary_key[0]
        python_type = column.type.python_type
        return python_type(raw_value)
    except (AttributeError, TypeError, ValueError, NotImplementedError):
        return raw_value


def user_password_attribute() -> str | None:
    columns = model_columns(User)
    if "password" in columns:
        return "password"
    if "password_hash" in columns:
        return "password_hash"
    return None


def get_user_password_hash(user: User) -> str:
    attribute = user_password_attribute()
    return str(getattr(user, attribute, "") or "") if attribute else ""


def set_user_password(user: User, plain_password: str) -> None:
    attribute = user_password_attribute()
    if not attribute:
        raise RuntimeError(
            "The User model needs either a 'password' or 'password_hash' column."
        )
    setattr(user, attribute, generate_password_hash(plain_password))


def get_model_time_column(model: type[db.Model]):
    for field in ("created_at", "timestamp", "updated_at", "id"):
        column = getattr(model, field, None)
        if column is not None:
            return column
    return None


def firebase_available() -> bool:
    return firestore_db is not None and bool(firebase_admin._apps)


def initialize_firebase(app: Flask) -> None:
    """Initialize Firebase without preventing Flask from starting."""
    global firestore_db
    firestore_db = None

    service_account_path = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_PATH",
        str(BASE_DIR / "serviceAccountKey.json"),
    )

    try:
        if not Path(service_account_path).exists():
            app.logger.warning(
                "Firebase service account file not found at %s. "
                "Local database login remains available.",
                service_account_path,
            )
            return

        if not firebase_admin._apps:
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)

        firestore_db = firestore.client()
        app.logger.info("Firebase Admin SDK initialized successfully.")
    except Exception:
        app.logger.exception(
            "Firebase initialization failed. Local database login remains available."
        )
        firestore_db = None


def create_app() -> Flask:
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
    )

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret-key-change-me"),
        SQLALCHEMY_DATABASE_URI=normalize_database_url(
            os.getenv("DATABASE_URL")
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=str(UPLOAD_FOLDER),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
        FIREBASE_API_KEY=os.getenv("FIREBASE_API_KEY", "").strip(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    )

    database_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if database_url.startswith("postgresql://"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 280,
            "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
            "connect_args": {
                "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
            },
        }

    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    AVATAR_FOLDER.mkdir(parents=True, exist_ok=True)

    CORS(
        app,
        resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*")}},
        supports_credentials=True,
    )
    db.init_app(app)
    migrate.init_app(app, db)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            key = model_primary_key_value(User, user_id)
            return db.session.get(User, key)
        except Exception:
            current_app.logger.exception("Could not load user %s", user_id)
            db.session.rollback()
            return None

    initialize_firebase(app)
    app.register_blueprint(analyzer_bp)

    return app


app = create_app()


class USSDLog(db.Model):
    __tablename__ = "ussd_logs"

    id = db.Column(db.Integer, primary_key=True)
    code_entered = db.Column(db.String(50))
    response_given = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=utcnow, nullable=False)


@app.cli.command("init-db")
def init_db_command() -> None:
    """Create tables after a new database has been attached."""
    db.create_all()
    print("Database tables created successfully.")


@app.cli.command("create-admin")
def create_admin_command() -> None:
    """
    Create or update the local administrator.

    Required Render environment variables:
    ADMIN_EMAIL, ADMIN_PASSWORD
    Optional: ADMIN_NAME
    """
    email = os.getenv("ADMIN_EMAIL", "admin@gmail.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "Nongwe@30admin")
    fullname = os.getenv("ADMIN_NAME", "System Administrator").strip()

    if not email or not password:
        raise RuntimeError(
            "Set ADMIN_EMAIL and ADMIN_PASSWORD before running create-admin."
        )
    if len(password) < 10:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 10 characters.")

    user = User.query.filter_by(email=email).first()
    if user is None:
        values = {
            "fullname": fullname,
            "username": os.getenv("ADMIN_USERNAME", "admin").strip(),
            "email": email,
            "phone": os.getenv("ADMIN_PHONE", "+254700000000"),
            "country": os.getenv("ADMIN_COUNTRY", "Kenya"),
            "county": os.getenv("ADMIN_COUNTY", "Nairobi"),
            "is_admin": True,
            "role": "admin",
            "created_at": utcnow(),
            "last_login": utcnow(),
            "streak_count": 1,
        }

        primary_key = User.__mapper__.primary_key[0]
        try:
            if primary_key.type.python_type is str:
                values[primary_key.name] = str(uuid.uuid4())
        except (AttributeError, NotImplementedError):
            pass

        user = User(**filtered_model_data(User, values))
        db.session.add(user)

    if hasattr(user, "is_admin"):
        user.is_admin = True
    if hasattr(user, "role"):
        user.role = "admin"

    set_user_password(user, password)
    db.session.commit()
    print(f"Administrator ready: {email}")


@app.errorhandler(413)
def upload_too_large(_error):
    message = "The uploaded file is too large. Maximum size is 20 MB."
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": message}), 413
    flash(message, "error")
    return redirect(request.referrer or url_for("home"))


@app.get("/health")
def health():
    """Render-compatible process health check without a database dependency."""
    return jsonify({"status": "ok", "service": "AgriTrue"}), 200


@app.get("/health/database")
def database_health():
    """Explicit database connectivity check."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("Database health check failed: %s", exc)
        return jsonify({"status": "error", "database": "unavailable"}), 503


def allowed_avatar(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_AVATAR_EXTENSIONS
    )


def update_login_streak(user: User) -> int:
    today = utcnow().date()
    streak = int(getattr(user, "streak_count", 1) or 1)
    last_login = getattr(user, "last_login", None)

    if last_login:
        last_date = last_login.date()
        if last_date == today - timedelta(days=1):
            streak += 1
        elif last_date < today - timedelta(days=1):
            streak = 1

    if hasattr(user, "streak_count"):
        user.streak_count = streak
    if hasattr(user, "last_login"):
        user.last_login = utcnow()

    return streak


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        is_admin = bool(getattr(current_user, "is_admin", False))
        role = str(getattr(current_user, "role", "") or "").lower()

        if not is_admin and role != "admin":
            flash("Access denied: administrators only.", "danger")
            return redirect(url_for("dashboard"))

        return view(*args, **kwargs)

    return wrapped


def sync_firestore_profile(uid: str, user_data: dict[str, Any]) -> None:
    if not firebase_available():
        return

    try:
        firestore_db.collection("users").document(uid).set(user_data, merge=True)
    except Exception:
        current_app.logger.exception(
            "Could not synchronize Firestore profile for %s", uid
        )


def firebase_sign_in(email: str, password: str) -> dict[str, Any] | None:
    api_key = current_app.config.get("FIREBASE_API_KEY", "")
    if not api_key:
        return None

    endpoint = (
        "https://identitytoolkit.googleapis.com/v1/"
        f"accounts:signInWithPassword?key={api_key}"
    )
    response = requests.post(
        endpoint,
        json={
            "email": email,
            "password": password,
            "returnSecureToken": True,
        },
        timeout=20,
    )

    try:
        payload = response.json()
    except ValueError:
        current_app.logger.warning(
            "Firebase login returned a non-JSON response: %s", response.status_code
        )
        return None

    return payload if response.ok and "localId" in payload else None


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/research")
def research():
    return render_template("research.html")


@app.route("/faqs")
def faqs():
    return render_template("faqs.html")


@app.route("/podcast")
def podcast():
    return render_template("podcast.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/donate")
def donate():
    return render_template("donate.html")


@app.post("/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    user_message = str(payload.get("message", "")).strip()

    if not user_message:
        return jsonify({"error": "No message provided."}), 400

    try:
        return jsonify({"reply": generate_farming_chat_reply(user_message)})
    except AnalyzerError as exc:
        current_app.logger.warning("Chat AI error: %s", exc)
        return jsonify({"error": str(exc)}), 503
    except Exception:
        current_app.logger.exception("Unexpected chat AI error")
        return jsonify({"error": "The assistant is temporarily unavailable."}), 500


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "GET":
        return render_template("register.html")

    fullname = request.form.get("fullname", "").strip()
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")
    phone = request.form.get("phone", "").strip()
    id_number = request.form.get("id_number", "").strip()
    home_address = request.form.get("home_address", "").strip()
    country = request.form.get("country", "").strip()
    county = request.form.get("county", "").strip()

    if not all((fullname, username, email, password, confirm_password)):
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("register"))

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("register"))

    if len(password) < 8:
        flash("Password must contain at least 8 characters.", "error")
        return redirect(url_for("register"))

    if phone and not re.fullmatch(r"\+\d{7,14}", phone):
        flash(
            "Use an international phone number such as +254712345678.",
            "error",
        )
        return redirect(url_for("register"))

    existing = User.query.filter(
        or_(User.email == email, User.username == username)
    ).first()
    if existing:
        flash("That email address or username is already registered.", "error")
        return redirect(url_for("register"))

    firebase_uid = None

    try:
        if firebase_available():
            firebase_user = auth.create_user(
                email=email,
                password=password,
                display_name=fullname,
                phone_number=phone or None,
            )
            firebase_uid = firebase_user.uid

        values = {
            "fullname": fullname,
            "username": username,
            "email": email,
            "phone": phone,
            "id_number": id_number,
            "home_address": home_address,
            "country": country,
            "county": county,
            "is_admin": False,
            "role": "user",
            "created_at": utcnow(),
            "last_login": utcnow(),
            "streak_count": 1,
        }

        primary_key = User.__mapper__.primary_key[0]
        try:
            if primary_key.type.python_type is str:
                values[primary_key.name] = firebase_uid or str(uuid.uuid4())
        except (AttributeError, NotImplementedError):
            pass

        user = User(**filtered_model_data(User, values))
        set_user_password(user, password)
        db.session.add(user)
        db.session.flush()

        firestore_uid = firebase_uid or str(user.id)
        sync_firestore_profile(
            firestore_uid,
            {
                "fullname": fullname,
                "username": username,
                "email": email,
                "phone": phone,
                "id_number": id_number,
                "home_address": home_address,
                "country": country,
                "county": county,
                "is_admin": False,
                "created_at": utcnow().isoformat(),
                "last_login": utcnow().isoformat(),
                "streak_count": 1,
                "local_user_id": str(user.id),
            },
        )

        db.session.commit()
        login_user(user)
        flash("Registration successful. Welcome to AgriTrue.", "success")
        return redirect(url_for("home"))

    except Exception as exc:
        db.session.rollback()

        if firebase_uid:
            try:
                auth.delete_user(firebase_uid)
            except Exception:
                current_app.logger.exception(
                    "Could not roll back Firebase user %s", firebase_uid
                )

        current_app.logger.exception("Registration failed")
        if exc.__class__.__name__ == "EmailAlreadyExistsError":
            flash("That email address is already registered.", "error")
        else:
            flash("Registration could not be completed. Please try again.", "error")
        return redirect(url_for("register"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Enter both your email address and password.", "error")
        return redirect(url_for("login"))

    db.session.rollback()
    local_user = User.query.filter_by(email=email).first()

    if local_user:
        password_hash = get_user_password_hash(local_user)
        if password_hash and check_password_hash(password_hash, password):
            streak = update_login_streak(local_user)
            db.session.commit()
            login_user(local_user, remember=True)
            flash(f"Logged in successfully. Current streak: {streak} days.", "success")
            return redirect(url_for("home"))

    try:
        firebase_payload = firebase_sign_in(email, password)
    except requests.RequestException:
        current_app.logger.exception("Firebase login request failed")
        firebase_payload = None

    if firebase_payload:
        uid = firebase_payload["localId"]
        user_data: dict[str, Any] = {}

        if firebase_available():
            try:
                profile = firestore_db.collection("users").document(uid).get()
                if profile.exists:
                    user_data = profile.to_dict() or {}
            except Exception:
                current_app.logger.exception("Could not load Firestore profile")

        user = local_user

        if user is None:
            values = {
                "fullname": user_data.get("fullname")
                or firebase_payload.get("displayName")
                or email.split("@")[0],
                "username": user_data.get("username")
                or f"user-{uid[:8]}",
                "email": email,
                "phone": user_data.get("phone", ""),
                "id_number": user_data.get("id_number", ""),
                "home_address": user_data.get("home_address", ""),
                "country": user_data.get("country", ""),
                "county": user_data.get("county", ""),
                "is_admin": bool(user_data.get("is_admin", False)),
                "role": "admin" if user_data.get("is_admin") else "user",
                "created_at": utcnow(),
                "streak_count": int(user_data.get("streak_count", 1) or 1),
            }

            primary_key = User.__mapper__.primary_key[0]
            try:
                if primary_key.type.python_type is str:
                    values[primary_key.name] = uid
            except (AttributeError, NotImplementedError):
                pass

            user = User(**filtered_model_data(User, values))
            set_user_password(user, password)
            db.session.add(user)
        elif not get_user_password_hash(user):
            set_user_password(user, password)

        streak = update_login_streak(user)
        db.session.commit()
        login_user(user, remember=True)

        sync_firestore_profile(
            uid,
            {
                "last_login": utcnow().isoformat(),
                "streak_count": streak,
                "local_user_id": str(user.id),
            },
        )

        flash(f"Logged in successfully. Current streak: {streak} days.", "success")
        return redirect(url_for("home"))

    flash("Invalid email address or password.", "error")
    return redirect(url_for("login"))


@app.get("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/community-notes", methods=["GET", "POST"])
@login_required
def community_notes():
    if request.method == "POST":
        note_text = request.form.get("note", "").strip()
        tags = request.form.get("tags", "").strip()

        if not note_text:
            flash("Note content cannot be empty.", "error")
            return redirect(url_for("community_notes"))

        values = {
            "note": note_text,
            "content": note_text,
            "tags": tags,
            "user_id": current_user.id,
            "timestamp": utcnow(),
            "created_at": utcnow(),
            "verified": False,
            "upvotes": 0,
        }

        try:
            db.session.add(
                CommunityNote(**filtered_model_data(CommunityNote, values))
            )
            db.session.commit()
            flash("Note posted successfully.", "success")
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Could not post community note")
            flash("The note could not be posted.", "error")

        return redirect(url_for("community_notes"))

    order_column = get_model_time_column(CommunityNote)
    query = CommunityNote.query
    if order_column is not None:
        query = query.order_by(desc(order_column))
    notes = query.all()

    enriched = []
    for note in notes:
        comment_order = get_model_time_column(Comment)
        comments_query = Comment.query.filter_by(note_id=note.id)
        if comment_order is not None:
            comments_query = comments_query.order_by(comment_order.asc())

        enriched.append(
            {
                "id": note.id,
                "content": getattr(note, "note", None)
                or getattr(note, "content", ""),
                "timestamp": getattr(note, "timestamp", None)
                or getattr(note, "created_at", None),
                "verified": bool(getattr(note, "verified", False)),
                "tags": getattr(note, "tags", ""),
                "upvotes": int(getattr(note, "upvotes", 0) or 0),
                "comments": comments_query.all(),
            }
        )

    return render_template("community_notes.html", notes=enriched)


@app.post("/comment/<int:note_id>")
@login_required
def post_comment(note_id: int):
    content = request.form.get("comment", "").strip()
    note = db.session.get(CommunityNote, note_id)

    if note is None:
        flash("Note not found.", "error")
        return redirect(url_for("community_notes"))

    if not content:
        flash("Comment cannot be empty.", "error")
        return redirect(url_for("community_notes"))

    values = {
        "text": content,
        "content": content,
        "note_id": note_id,
        "user_id": current_user.id,
        "created_at": utcnow(),
        "timestamp": utcnow(),
    }

    try:
        db.session.add(Comment(**filtered_model_data(Comment, values)))
        db.session.commit()
        flash("Comment added.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not add comment")
        flash("The comment could not be added.", "error")

    return redirect(url_for("community_notes"))


@app.post("/verify/<int:note_id>")
@admin_required
def mark_verified(note_id: int):
    note = db.session.get(CommunityNote, note_id)
    if note is None:
        return jsonify({"status": "not found"}), 404

    if hasattr(note, "verified"):
        note.verified = True
    db.session.commit()
    return jsonify({"status": "verified"})


@app.post("/upvote/<int:note_id>")
@login_required
def upvote(note_id: int):
    note = db.session.get(CommunityNote, note_id)
    if note is None:
        return jsonify({"status": "not found"}), 404

    voted_notes = set(session.get("voted_notes", []))
    if note_id in voted_notes:
        return jsonify({"status": "already upvoted"}), 400

    note.upvotes = int(getattr(note, "upvotes", 0) or 0) + 1
    db.session.commit()

    voted_notes.add(note_id)
    session["voted_notes"] = list(voted_notes)
    return jsonify({"status": "upvoted", "upvotes": note.upvotes})


@app.post("/repost/<int:note_id>")
@login_required
def repost(note_id: int):
    source = db.session.get(CommunityNote, note_id)
    if source is None:
        return jsonify({"status": "not found"}), 404

    note_text = getattr(source, "note", None) or getattr(source, "content", "")
    values = {
        "note": note_text,
        "content": note_text,
        "tags": getattr(source, "tags", ""),
        "reposted_from": note_id,
        "user_id": current_user.id,
        "timestamp": utcnow(),
        "created_at": utcnow(),
        "upvotes": 0,
        "verified": False,
    }

    try:
        new_note = CommunityNote(
            **filtered_model_data(CommunityNote, values)
        )
        db.session.add(new_note)
        db.session.commit()
        return jsonify({"status": "reposted", "new_note_id": new_note.id})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not repost community note")
        return jsonify({"status": "error"}), 500


@app.route("/ussd", methods=["GET", "POST"])
def ussd():
    menu = """
    Welcome to <strong>AgriTrue</strong> USSD Services<br>
    1. Weather Info<br>
    2. Altitude Data<br>
    3. Soil Type<br>
    4. Pest Alerts<br>
    5. Crop Pricing<br>
    6. Market Locations<br>
    7. Expert Advice<br>
    8. Innovations<br>
    9. Misinformation Alerts<br>
    10. Exit
    """

    if request.method == "GET":
        return render_template("ussd.html", response=None, session_level="")

    ussd_code = request.form.get("ussd_code", "").strip()
    session_level = request.form.get("session_level", "")

    if ussd_code == "*456#" and session_level == "":
        response = menu
        session_level = "main_menu"
    elif session_level == "main_menu":
        responses = {
            "1": "☀ Weather Today: Sunny, 28°C",
            "2": "🗻 Altitude at your location: 1,450 metres",
            "3": "🌱 Soil Type: Loamy",
            "4": "🐛 Pest Alert: Fall armyworm in maize.",
            "5": "💰 Maize: KES 45/kg, Beans: KES 80/kg",
            "6": "🛒 Nearest Market: Machakos Open Market",
            "7": "🧠 Tip: Rotate crops to improve soil fertility.",
            "8": "💡 Innovation: AI-powered irrigation.",
            "9": "🚫 Claim review: boiling seeds does not increase yield.",
            "10": "👋 Thank you for using AgriTrue.",
        }
        response = responses.get(ussd_code, "❌ Invalid option. Try again.")
        session_level = ""
    else:
        response = "Enter *456# to begin."

    try:
        db.session.add(
            USSDLog(code_entered=ussd_code, response_given=response)
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save USSD log")

    return render_template(
        "ussd.html",
        response=response,
        session_level=session_level,
    )


@app.get("/chatbot")
def chatbot_page():
    return render_template("chatbot.html")


@app.post("/chatbot")
def chatbot_reply():
    payload = request.get_json(silent=True) or {}
    user_input = str(
        payload.get("user_input") or payload.get("message") or ""
    ).strip()

    if not user_input:
        return jsonify({"response": "No input received."}), 400

    try:
        return jsonify({"response": generate_farming_chat_reply(user_input)})
    except AnalyzerError as exc:
        return jsonify({"response": str(exc)}), 503
    except Exception:
        current_app.logger.exception("Chatbot failed")
        return jsonify({"response": "The assistant is temporarily unavailable."}), 500


@app.post("/chatbot/voice")
def voice_chatbot():
    audio = request.files.get("audio")
    if audio is None or not audio.filename:
        return jsonify({"response": "No audio file was received."}), 400

    suffix = Path(secure_filename(audio.filename)).suffix or ".wav"
    path = UPLOAD_FOLDER / f"voice-{uuid.uuid4().hex}{suffix}"
    audio.save(path)

    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(path)) as source:
            audio_data = recognizer.record(source)

        user_input = recognizer.recognize_google(audio_data)
        return jsonify({"response": generate_farming_chat_reply(user_input)})
    except sr.UnknownValueError:
        return jsonify(
            {"response": "I could not understand the recording. Please try again."}
        ), 422
    except Exception:
        current_app.logger.exception("Voice chatbot failed")
        return jsonify(
            {"response": "The voice request could not be processed."}
        ), 500
    finally:
        path.unlink(missing_ok=True)


@app.post("/whatsapp")
def whatsapp_reply():
    incoming_message = request.form.get("Body", "").strip()
    response = MessagingResponse()
    message = response.message()

    if not incoming_message:
        message.body("Please send an agriculture-related question.")
        return str(response)

    try:
        message.body(generate_farming_chat_reply(incoming_message))
    except AnalyzerError as exc:
        message.body(str(exc))
    except Exception:
        current_app.logger.exception("WhatsApp assistant failed")
        message.body("The AgriTrue assistant is temporarily unavailable.")

    return str(response)




mock_data = {
    "kirinyaga": {
        "soil_type": "Clay Loam",
        "ph": 5.5,
        "weather": "Rainy, 18-24°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "kitale": {
        "soil_type": "Sandy Loam",
        "ph": 6.3,
        "weather": "Mild, 20-27°C",
        "crop": "Maize",
        "fertilizer": "DAP + CAN"
    },
    "nyeri": {
        "soil_type": "Loam",
        "ph": 6.0,
        "weather": "Cool, 16-22°C",
        "crop": "Coffee",
        "fertilizer": "NPK 20:10:10"
    },
    "nakuru": {
        "soil_type": "Volcanic Ash",
        "ph": 6.5,
        "weather": "Cool and wet, 15-22°C",
        "crop": "Potatoes",
        "fertilizer": "CAN + Organic Compost"
    },
    "bungoma": {
        "soil_type": "Clay",
        "ph": 5.8,
        "weather": "Humid, 22-28°C",
        "crop": "Sugarcane",
        "fertilizer": "NPK 18:18:18"
    },
    "meru": {
        "soil_type": "Red Loam",
        "ph": 5.7,
        "weather": "Cool, 17-23°C",
        "crop": "Miraa",
        "fertilizer": "NPK 17:17:17"
    },
    "embu": {
        "soil_type": "Clay Loam",
        "ph": 5.9,
        "weather": "Warm, 19-25°C",
        "crop": "Macadamia",
        "fertilizer": "Organic Manure"
    },
    "machakos": {
        "soil_type": "Sandy",
        "ph": 6.2,
        "weather": "Dry, 20-28°C",
        "crop": "Mangoes",
        "fertilizer": "Compost"
    },
    "makueni": {
        "soil_type": "Sandy Loam",
        "ph": 6.1,
        "weather": "Hot, 22-30°C",
        "crop": "Oranges",
        "fertilizer": "NPK 15:15:15"
    },
    "kisii": {
        "soil_type": "Clay Loam",
        "ph": 5.6,
        "weather": "Wet, 18-24°C",
        "crop": "Bananas",
        "fertilizer": "Organic Compost"
    },
    "homabay": {
        "soil_type": "Black Cotton",
        "ph": 6.0,
        "weather": "Warm, 21-29°C",
        "crop": "Cotton",
        "fertilizer": "NPK 20:10:10"
    },
    "kisumu": {
        "soil_type": "Alluvial",
        "ph": 6.4,
        "weather": "Hot, 23-32°C",
        "crop": "Rice",
        "fertilizer": "Urea"
    },
    "siaya": {
        "soil_type": "Clay",
        "ph": 5.8,
        "weather": "Humid, 22-28°C",
        "crop": "Sorghum",
        "fertilizer": "NPK 17:17:17"
    },
    "busia": {
        "soil_type": "Loam",
        "ph": 6.2,
        "weather": "Wet, 20-27°C",
        "crop": "Groundnuts",
        "fertilizer": "Organic Manure"
    },
    "kakamega": {
        "soil_type": "Clay Loam",
        "ph": 5.7,
        "weather": "Humid, 19-26°C",
        "crop": "Sugarcane",
        "fertilizer": "NPK 18:18:18"
    },
    "trans nzoia": {
        "soil_type": "Silty Loam",
        "ph": 6.3,
        "weather": "Cool, 17-23°C",
        "crop": "Wheat",
        "fertilizer": "DAP"
    },
    "uasin gishu": {
        "soil_type": "Loam",
        "ph": 6.5,
        "weather": "Cool, 15-22°C",
        "crop": "Barley",
        "fertilizer": "CAN"
    },
    "bomet": {
        "soil_type": "Clay Loam",
        "ph": 5.9,
        "weather": "Cool, 16-22°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "kericho": {
        "soil_type": "Volcanic",
        "ph": 5.6,
        "weather": "Wet, 15-21°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "narok": {
        "soil_type": "Sandy Loam",
        "ph": 6.0,
        "weather": "Cool, 14-22°C",
        "crop": "Wheat",
        "fertilizer": "DAP"
    },
    "nyandarua": {
        "soil_type": "Peaty",
        "ph": 5.8,
        "weather": "Cool, 12-20°C",
        "crop": "Cabbages",
        "fertilizer": "Organic Compost"
    },
    "laikipia": {
        "soil_type": "Sandy",
        "ph": 6.3,
        "weather": "Dry, 18-26°C",
        "crop": "Tomatoes",
        "fertilizer": "NPK 17:17:17"
    },
    "turkana": {
        "soil_type": "Sandy",
        "ph": 7.0,
        "weather": "Hot, 28-38°C",
        "crop": "Millet",
        "fertilizer": "Organic Manure"
    },
    "garissa": {
        "soil_type": "Sandy",
        "ph": 7.2,
        "weather": "Hot, 30-40°C",
        "crop": "Watermelon",
        "fertilizer": "Compost"
    },
    "wajir": {
        "soil_type": "Sandy",
        "ph": 7.3,
        "weather": "Hot, 32-42°C",
        "crop": "Sorghum",
        "fertilizer": "Organic Manure"
    },
    "mandera": {
        "soil_type": "Sandy",
        "ph": 7.4,
        "weather": "Hot, 33-43°C",
        "crop": "Green grams",
        "fertilizer": "Compost"
    },
    "nyamira": {
        "soil_type": "Clay Loam",
        "ph": 5.6,
        "weather": "Wet, 18-24°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "tharaka nithi": {
        "soil_type": "Clay Loam",
        "ph": 5.9,
        "weather": "Warm, 19-25°C",
        "crop": "Macadamia",
        "fertilizer": "Organic Manure"
    },
    "kiambu": {
        "soil_type": "Loam",
        "ph": 6.0,
        "weather": "Cool, 16-22°C",
        "crop": "Coffee",
        "fertilizer": "NPK 20:10:10"
    },
    "murang'a": {
        "soil_type": "Clay Loam",
        "ph": 5.8,
        "weather": "Cool, 18-24°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "nairobi": {
        "soil_type": "Clay",
        "ph": 6.2,
        "weather": "Mild, 20-27°C",
        "crop": "Vegetables",
        "fertilizer": "Compost"
    },
    "kwale": {
        "soil_type": "Sandy",
        "ph": 6.5,
        "weather": "Hot, 25-32°C",
        "crop": "Coconuts",
        "fertilizer": "Organic Manure"
    },
    "mombasa": {
        "soil_type": "Sandy",
        "ph": 6.8,
        "weather": "Hot, 28-34°C",
        "crop": "Cashew Nuts",
        "fertilizer": "Compost"
    },
    "kilifi": {
        "soil_type": "Sandy",
        "ph": 6.7,
        "weather": "Hot, 27-33°C",
        "crop": "Mangoes",
        "fertilizer": "Organic Manure"
    },
    "tana river": {
        "soil_type": "Alluvial",
        "ph": 6.4,
        "weather": "Hot, 26-35°C",
        "crop": "Rice",
        "fertilizer": "Urea"
    },
    "lamu": {
        "soil_type": "Sandy",
        "ph": 6.6,
        "weather": "Hot, 27-34°C",
        "crop": "Coconuts",
        "fertilizer": "Compost"
    },
    "isiolo": {
        "soil_type": "Sandy",
        "ph": 7.1,
        "weather": "Hot, 29-38°C",
        "crop": "Millet",
        "fertilizer": "Organic Manure"
    },
    "marsabit": {
        "soil_type": "Sandy",
        "ph": 7.3,
        "weather": "Hot, 30-40°C",
        "crop": "Sorghum",
        "fertilizer": "Compost"
    },
    "samburu": {
        "soil_type": "Sandy Loam",
        "ph": 6.8,
        "weather": "Hot, 25-35°C",
        "crop": "Maize",
        "fertilizer": "DAP"
    },
    "elgeyo marakwet": {
        "soil_type": "Loam",
        "ph": 6.3,
        "weather": "Cool, 17-23°C",
        "crop": "Wheat",
        "fertilizer": "CAN"
    },
    "west pokot": {
        "soil_type": "Clay Loam",
        "ph": 5.9,
        "weather": "Cool, 16-22°C",
        "crop": "Maize",
        "fertilizer": "NPK 17:17:17"
    },
    "vihiga": {
        "soil_type": "Clay Loam",
        "ph": 5.7,
        "weather": "Humid, 19-26°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "nandi": {
        "soil_type": "Loam",
        "ph": 6.0,
        "weather": "Cool, 16-22°C",
        "crop": "Tea",
        "fertilizer": "NPK 25:5:5"
    },
    "taita taveta": {
        "soil_type": "Sandy Loam",
        "ph": 6.2,
        "weather": "Warm, 20-28°C",
        "crop": "Pineapples",
        "fertilizer": "Compost"
    }
}



@app.route("/know_your_land", methods=["GET", "POST"])
@login_required
def know_your_land():
    results = {}
    selected_county = ""

    if request.method == "POST":
        selected_county = request.form.get("county", "").strip().lower()
        results = mock_data.get(selected_county, {})

        if not results:
            flash("No county information was found for that selection.", "info")

    return render_template(
        "know_your_land.html",
        results=results,
        selected_county=selected_county,
    )


@app.get("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user)


@app.route("/edit_profile", methods=["GET", "POST"])
@login_required
def edit_profile():
    user = current_user

    if request.method == "GET":
        return render_template("edit_profile.html", user=user)

    new_username = request.form.get("username", "").strip()
    new_fullname = request.form.get("fullname", "").strip()
    new_email = request.form.get("email", "").strip().lower()
    new_phone = request.form.get("phone", "").strip()
    new_country = request.form.get("country", "").strip()
    new_county = request.form.get("county", "").strip()
    new_password = request.form.get("password", "")

    if new_username and new_username != getattr(user, "username", ""):
        duplicate = User.query.filter_by(username=new_username).first()
        if duplicate and duplicate.id != user.id:
            flash("Username already taken. Choose another one.", "error")
            return redirect(url_for("edit_profile"))

    if new_email and new_email != getattr(user, "email", ""):
        duplicate = User.query.filter_by(email=new_email).first()
        if duplicate and duplicate.id != user.id:
            flash("Email address already registered.", "error")
            return redirect(url_for("edit_profile"))

    field_values = {
        "username": new_username,
        "fullname": new_fullname,
        "email": new_email,
        "phone": new_phone,
        "country": new_country,
        "county": new_county,
    }

    for field, value in field_values.items():
        if hasattr(user, field) and value:
            setattr(user, field, value)

    if new_password:
        if len(new_password) < 8:
            flash("A new password must contain at least 8 characters.", "error")
            return redirect(url_for("edit_profile"))
        set_user_password(user, new_password)

    try:
        db.session.commit()
        flash("Profile updated successfully.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Profile update failed")
        flash("Your profile could not be updated.", "error")

    return redirect(url_for("profile"))


@app.post("/upload_avatar")
@login_required
def upload_avatar():
    uploaded = request.files.get("avatar")

    if uploaded is None or not uploaded.filename:
        flash("Select an avatar image first.", "error")
        return redirect(url_for("edit_profile"))

    if not allowed_avatar(uploaded.filename):
        flash("Allowed avatar types: PNG, JPG, JPEG and WEBP.", "error")
        return redirect(url_for("edit_profile"))

    extension = uploaded.filename.rsplit(".", 1)[1].lower()
    filename = f"avatar-{current_user.id}-{uuid.uuid4().hex}.{extension}"
    destination = AVATAR_FOLDER / filename

    try:
        uploaded.save(destination)

        if not hasattr(current_user, "avatar_url"):
            destination.unlink(missing_ok=True)
            flash("The User model does not contain an avatar_url field.", "error")
            return redirect(url_for("edit_profile"))

        old_avatar = getattr(current_user, "avatar_url", "") or ""
        current_user.avatar_url = url_for(
            "static",
            filename=f"avatars/{filename}",
        )
        db.session.commit()

        if old_avatar.startswith("/static/avatars/"):
            old_name = Path(old_avatar).name
            if old_name != filename:
                (AVATAR_FOLDER / old_name).unlink(missing_ok=True)

        flash("Avatar uploaded successfully.", "success")
    except Exception:
        db.session.rollback()
        destination.unlink(missing_ok=True)
        current_app.logger.exception("Avatar upload failed")
        flash("The avatar could not be uploaded.", "error")

    return redirect(url_for("edit_profile"))


@app.route("/streak")
@app.route("/streak/<username>")
def streak(username=None):
    if username:
        user_to_show = User.query.filter_by(username=username).first()
        if user_to_show is None:
            flash("That user does not exist.", "error")
            return redirect(url_for("home"))
    else:
        if not current_user.is_authenticated:
            flash("Log in to view your streak.", "info")
            return redirect(url_for("login"))
        user_to_show = current_user

    return render_template("streak.html", user=user_to_show)


@app.get("/admin")
@admin_required
def admin_dashboard():
    def ordered(model):
        order_column = get_model_time_column(model)
        query = model.query
        return (
            query.order_by(desc(order_column)).all()
            if order_column is not None
            else query.all()
        )

    users = ordered(User)
    notes = ordered(CommunityNote)
    diagnostics = ordered(DiagnosticResult)
    comments = ordered(Comment)

    return render_template(
        "admin_dashboard.html",
        users=users,
        notes=notes,
        diagnostics=diagnostics,
        comments=comments,
        total_users=len(users),
        total_notes=len(notes),
        total_diagnostics=len(diagnostics),
        total_comments=len(comments),
    )


@app.post("/admin/delete_user/<string:user_id>")
@admin_required
def delete_user_admin(user_id: str):
    key = model_primary_key_value(User, user_id)
    user = db.session.get(User, key)

    if user is None:
        abort(404)

    if user.id == current_user.id:
        flash("You cannot delete your own administrator account.", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        db.session.delete(user)
        db.session.commit()
        flash("User deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Admin user deletion failed")
        flash("The user could not be deleted.", "danger")

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/delete_note/<int:note_id>")
@admin_required
def delete_note_admin(note_id: int):
    note = db.session.get(CommunityNote, note_id)
    if note is None:
        abort(404)

    try:
        db.session.delete(note)
        db.session.commit()
        flash("Note deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Admin note deletion failed")
        flash("The note could not be deleted.", "danger")

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/delete_diagnostic/<int:diagnostic_id>")
@admin_required
def delete_diagnostic_admin(diagnostic_id: int):
    diagnostic = db.session.get(DiagnosticResult, diagnostic_id)
    if diagnostic is None:
        abort(404)

    try:
        image_url = getattr(diagnostic, "image_url", "") or ""
        db.session.delete(diagnostic)
        db.session.commit()

        if image_url.startswith("/uploads/"):
            (UPLOAD_FOLDER / Path(image_url).name).unlink(missing_ok=True)

        flash("Diagnostic deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Admin diagnostic deletion failed")
        flash("The diagnostic could not be deleted.", "danger")

    return redirect(url_for("admin_dashboard"))


@app.post("/admin/delete_comment/<int:comment_id>")
@admin_required
def delete_comment_admin(comment_id: int):
    comment = db.session.get(Comment, comment_id)
    if comment is None:
        abort(404)

    try:
        db.session.delete(comment)
        db.session.commit()
        flash("Comment deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Admin comment deletion failed")
        flash("The comment could not be deleted.", "danger")

    return redirect(url_for("admin_dashboard"))


@app.post("/log_analysis")
@login_required
def log_analysis():
    payload = request.get_json(silent=True) or {}

    values = {
        "user_id": current_user.id,
        "image_url": payload.get("image_url")
        or payload.get("filename", ""),
        "diagnosis_name": payload.get("diagnosis_name")
        or payload.get("summary", "Unknown"),
        "diagnosis_type": payload.get("diagnosis_type")
        or payload.get("type", "unknown"),
        "cause": payload.get("cause", "Not established"),
        "treatment": payload.get("treatment", "Professional review advised"),
        "confidence_score": payload.get("confidence_score")
        or payload.get("confidence"),
        "created_at": utcnow(),
    }

    try:
        diagnostic = DiagnosticResult(
            **filtered_model_data(DiagnosticResult, values)
        )
        db.session.add(diagnostic)
        db.session.commit()
        return jsonify({"status": "success", "id": diagnostic.id})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not log diagnostic analysis")
        return jsonify({"status": "error"}), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )