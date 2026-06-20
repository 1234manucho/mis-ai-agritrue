from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from sqlalchemy import desc
import os
import re
import requests
import json
import uuid
from datetime import datetime, timedelta

import docx
from PyPDF2 import PdfReader
from PIL import Image

# ------------------- LOCAL IMPORTS -------------------
from extensions import db, migrate
from models import CommunityNote, Comment, User, DiagnosticResult

# ------------------- FIREBASE -------------------
import firebase_admin
from firebase_admin import credentials, auth, firestore

# ------------------- GOOGLE GENERATIVE AI -------------------
import google.generativeai as genai
genai.configure(api_key="AIzaSyCy7NQ0LzkmJWERKGhZtyyfcyXswyWmdZU")
model = genai.GenerativeModel("gemini-2.0-flash")


# ------------------- OPENAI -------------------
import openai
openai.api_key = "AIzaSyCy7NQ0LzkmJWERKGhZtyyfcyXswyWmdZU"

# ------------------- APP FACTORY -------------------
def create_app():
    app = Flask(__name__)
    CORS(app)

    app.secret_key = 'supersecretkey'
    app.config['UPLOAD_FOLDER'] = 'uploads/'
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agritrue.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['FIREBASE_API_KEY'] = "AIzaSyBnnfskPKX1-0jYeIDa1Ua6i0UkqWy6ImI"


    # ------------------- EXTENSIONS -------------------
    db.init_app(app)
    migrate.init_app(app, db)

    # ------------------- LOGIN -------------------
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    # ------------------- FIREBASE INITIALIZATION -------------------
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
            print("Firebase Admin SDK initialized successfully.")
        except Exception as e:
            print(f"Error initializing Firebase Admin SDK: {e}")

    global firestore_db
    firestore_db = firestore.client()

    return app

# ------------------- CREATE APP INSTANCE -------------------
app = create_app()

# ------------------- FILE UTILS -------------------
ALLOWED_EXTENSIONS = {'csv', 'pdf', 'docx', 'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ------------------- FIREBASE API KEY HELPER -------------------
def get_firebase_api_key():
    return current_app.config.get('FIREBASE_API_KEY')
@app.route('/setup-admin')
def setup_admin():
   

    from firebase_admin import auth

    # ---- CHANGE THESE ----
    admin_email = "admin@agritrue.org"
    admin_password = "admin@30"   # Change to a strong password
    admin_name = "System Administrator"

    try:
        # ✅ Try to find admin in Firebase Auth
        user_record = auth.get_user_by_email(admin_email)
        uid = user_record.uid
        print("Admin already exists in Firebase Auth.")
    except:
        # ✅ Create the admin in Firebase Auth
        user_record = auth.create_user(
            email=admin_email,
            password=admin_password,
            display_name=admin_name
        )
        uid = user_record.uid
        print("Admin created in Firebase Auth.")

    # ✅ Ensure Firestore profile exists
    user_ref = firestore_db.collection("users").document(uid)
    user_ref.set({
        "fullname": admin_name,
        "email": admin_email,
        "username": "admin",
        "phone": "+254700000000",
        "id_number": "000000000",
        "home_address": "Nairobi",
        "country": "Kenya",
        "county": "Nairobi",
        "is_admin": True,
        "streak_count": 1,
        "last_login": datetime.utcnow().isoformat()
    }, merge=True)

    # ✅ Ensure Local DB sync with hashed password
    existing_local = db.session.get(User, uid)
    hashed_pw = generate_password_hash(admin_password)

    if not existing_local:
        new_admin = User(
            id=uid,
            fullname=admin_name,
            username="admin",
            email=admin_email,
            password=hashed_pw,  # ✅ hashed password added
            phone="+254700000000",
            id_number="000000000",
            home_address="Nairobi",
            country="Kenya",
            county="Nairobi",
            is_admin=True,
            created_at=datetime.utcnow(),
            streak_count=1,
            last_login=datetime.utcnow()
        )
        db.session.add(new_admin)
        db.session.commit()
        print("Admin added to local database.")
    else:
        existing_local.is_admin = True
        existing_local.password = hashed_pw  # ✅ update hashed password if already exists
        db.session.commit()
        print("Admin updated in local database.")

    return "✅ Admin setup complete. You can now login as admin.<br><br>IMPORTANT: Remove /setup-admin route now."
# ----------------- ROUTES -----------------

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')


# --- Chatbot API ---
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        prompt = f"You are AgriTrue, an expert agricultural AI. Respond to the user's query concisely and only about farming. User's query: {user_message}"
        response = model.generate_content(prompt)
        response_text = "".join([part.text for part in response.candidates[0].content.parts if hasattr(part, 'text')])

        if not response_text:
            response_text = "I'm sorry, I couldn't generate a response this time. Please try a different query."

        return jsonify({"reply": response_text})
    except Exception as e:
        print(f"Error during AI call: {e}")
        return jsonify({"error": "Server error. Could not get response."}), 500
# --- Registration Route ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    """Register user in Firebase Auth + Firestore + SQLAlchemy"""
    if request.method == 'POST':
        fullname = request.form.get('fullname', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        phone = request.form.get('phone', '').strip()
        id_number = request.form.get('id_number', '').strip()
        home_address = request.form.get('home_address', '').strip()
        country = request.form.get('country', '').strip()
        county = request.form.get('county', '').strip()

        # --- Validation ---
        if not all([fullname, username, email, password, confirm_password]):
            flash("Please fill in all required fields.", "error")
            return redirect(url_for('register'))

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for('register'))

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return redirect(url_for('register'))

        if phone and not re.match(r"^\+\d{1,14}$", phone):
            flash("Invalid phone number. Use international format (e.g., +260971234567).", "error")
            return redirect(url_for('register'))

        # ✅ SQLAlchemy 2.0: use select() instead of query.filter_by
        existing_user = db.session.execute(
            db.select(User).filter_by(username=username)
        ).scalar_one_or_none()
        if existing_user:
            flash("Username already exists.", "error")
            return redirect(url_for('register'))

        try:
            # 1. Create Firebase Auth User
            firebase_user = auth.create_user(
                email=email,
                password=password,
                display_name=fullname,
                phone_number=phone if phone else None
            )
            uid = firebase_user.uid

            # 2. Firestore Data
            user_data = {
                "fullname": fullname,
                "username": username,
                "email": email,
                "phone": phone,
                "id_number": id_number,
                "home_address": home_address,
                "country": country,
                "county": county,
                "is_admin": False,
                "created_at": datetime.utcnow().isoformat(),
                "last_login": datetime.utcnow().isoformat(),
                "streak_count": 1
            }
            firestore_db.collection("users").document(uid).set(user_data)

            # 3. Local DB
            new_user = User(
                id=uid,
                fullname=fullname,
                username=username,
                email=email,
                phone=phone,
                id_number=id_number,
                home_address=home_address,
                country=country,
                county=county
            )
            db.session.add(new_user)
            db.session.commit()

            flash("✅ Registration successful! Welcome.", "success")
            return redirect(url_for('community_notes'))

        except firebase_admin._auth_utils.EmailAlreadyExistsError:
            flash("Email already registered. Please log in.", "error")
            return redirect(url_for('register'))
        except Exception as e:
            db.session.rollback()
            flash(f"⚠️ Internal error: {str(e)}", "error")
            return redirect(url_for('register'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Rollback any pending transaction to avoid PendingRollbackError
    db.session.rollback()

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return redirect(url_for('login'))

        # --- 1️⃣ Try Firebase Login ---
        try:
            firebase_api_key = current_app.config.get('FIREBASE_API_KEY')
            if not firebase_api_key:
                raise ValueError("Firebase API key is not configured.")

            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={firebase_api_key}"
            payload = {"email": email, "password": password, "returnSecureToken": True}
            headers = {"Content-Type": "application/json"}
            res = requests.post(url, data=json.dumps(payload), headers=headers)
            res_data = res.json()

            if "error" not in res_data:
                uid = res_data["localId"]

                # --- Fetch Firestore Profile ---
                user_ref = firestore_db.collection("users").document(uid)
                user_doc = user_ref.get()

                if not user_doc.exists:
                    flash("User profile missing in Firestore. Contact support.", "error")
                    return redirect(url_for('login'))

                user_data = user_doc.to_dict()

                # --- Streak Count Update (using timezone-aware UTC) ---
                from datetime import timezone
                today = datetime.now(timezone.utc).date()
                streak = user_data.get("streak_count", 1)
                last_login = user_data.get("last_login")

                last_login_date = None
                if last_login:
                    try:
                        if isinstance(last_login, str):
                            last_login_date = datetime.fromisoformat(last_login).date()
                        else:
                            last_login_date = last_login.date()
                    except:
                        last_login_date = today

                if last_login_date == today - timedelta(days=1):
                    streak += 1
                elif last_login_date and last_login_date < today - timedelta(days=1):
                    streak = 1

                user_ref.update({
                    "streak_count": streak,
                    "last_login": datetime.now(timezone.utc).isoformat()
                })

                # --- Sync / Create Local User Record ---
                user = db.session.get(User, uid)
                if not user:
                    user = User(
                        id=uid,
                        fullname=user_data.get('fullname'),
                        username=user_data.get('username'),
                        email=user_data.get('email'),
                        phone=user_data.get('phone'),
                        id_number=user_data.get('id_number'),
                        home_address=user_data.get('home_address'),
                        country=user_data.get('country'),
                        county=user_data.get('county'),
                        is_admin=user_data.get('is_admin', False),
                        created_at=datetime.now(timezone.utc),
                        streak_count=streak,
                        last_login=datetime.now(timezone.utc)
                    )
                    db.session.add(user)
                else:
                    user.streak_count = streak
                    user.last_login = datetime.now(timezone.utc)

                db.session.commit()
                login_user(user)

                flash(f"✅ Logged in successfully! Streak: {streak} days.", "success")
                return redirect(url_for('home'))

        except Exception as e:
            # Log the error for debugging but continue to local login
            print(f"Firebase login error: {e}")
            db.session.rollback()  # ensure session is clean for local attempt

        # --- 2️⃣ Local Admin / Local DB Login (only accounts with stored password) ---
        local_user = User.query.filter_by(email=email).first()

        # If user exists but has no password → It's Firebase-linked → Do not check hash
        if local_user and not local_user.password:
            flash("This account uses Firebase authentication. Please log in using the password you used when registering.", "error")
            return redirect(url_for('login'))

        # If Local user has password → Check normally
        if local_user and local_user.password and check_password_hash(local_user.password, password):
            from datetime import timezone
            today = datetime.now(timezone.utc).date()
            last_login_date = local_user.last_login.date() if local_user.last_login else today

            if last_login_date == today - timedelta(days=1):
                local_user.streak_count += 1
            elif last_login_date < today - timedelta(days=1):
                local_user.streak_count = 1

            local_user.last_login = datetime.now(timezone.utc)
            db.session.commit()

            login_user(local_user)
            flash(f"✅ Logged in (Local Account). Streak: {local_user.streak_count} days.", "success")
            return redirect(url_for('home'))

        flash("Invalid login credentials.", "error")
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/community-notes', methods=['GET', 'POST'])
@login_required
def community_notes():
    if request.method == 'POST':
        note = request.form.get('note', '').strip()
        tags = request.form.get('tags', '').strip()
        if not note:
            flash("Note content cannot be empty.", "error")
        else:
            new_note = CommunityNote(
                note=note,
                tags=tags,
                user_id=current_user.id
            )
            db.session.add(new_note)
            db.session.commit()
            flash("Note posted successfully!", "success")
        return redirect(url_for('community_notes'))

    notes = CommunityNote.query.order_by(desc(CommunityNote.timestamp)).all()
    enriched = []
    for n in notes:
        comments = Comment.query.filter_by(note_id=n.id).order_by(Comment.created_at.asc()).all()

        enriched.append({
            "id": n.id,
            "content": n.note,
            "timestamp": n.timestamp,
            "verified": n.verified,
            "tags": n.tags,
            "upvotes": n.upvotes,
            "comments": comments
        })

    return render_template('community_notes.html', notes=enriched)
@app.route('/comment/<int:note_id>', methods=['POST'])
def post_comment(note_id):
    content = request.form.get('comment', '').strip()
    if content:
        note_exists = CommunityNote.query.get(note_id)
        if not note_exists:
            flash("Note not found.", "error")
            return redirect(url_for('community_notes'))

        new_comment = Comment(
    text=content,              # ✅ must match model field
    note_id=note_id,
    user_id=current_user.id,   # ✅ required since Comment has user_id FK
    created_at=datetime.utcnow()
)

        db.session.add(new_comment)
        db.session.commit()
        flash("Comment added!", "success")
    else:
        flash("Comment cannot be empty.", "error")

    return redirect(url_for('community_notes'))


@app.route('/verify/<int:note_id>', methods=['POST'])
def mark_verified(note_id):
    note = CommunityNote.query.get(note_id)
    if note:
        note.verified = True
        db.session.commit()
        return jsonify({'status': 'verified'})
    return jsonify({'status': 'not found'}), 404


@app.route('/upvote/<int:note_id>', methods=['POST'])
def upvote(note_id):
    note = CommunityNote.query.get(note_id)
    if not note:
        return jsonify({'status': 'not found'}), 404

    # Prevent duplicate upvotes from same session
    voted_notes = session.get('voted_notes', [])
    if note_id in voted_notes:
        return jsonify({'status': 'already upvoted'}), 400

    note.upvotes += 1
    db.session.commit()

    voted_notes.append(note_id)
    session['voted_notes'] = voted_notes

    return jsonify({'status': 'upvoted', 'upvotes': note.upvotes})


@app.route('/repost/<int:note_id>', methods=['POST'])
def repost(note_id):
    note = CommunityNote.query.get(note_id)
    if note:
        new_note = CommunityNote(
            note=note.note,
            tags=note.tags,
            reposted_from=note_id,
            timestamp=datetime.utcnow(),
            upvotes=0,
            verified=False
        )
        db.session.add(new_note)
        db.session.commit()
        return jsonify({'status': 'reposted', 'new_note_id': new_note.id})
    return jsonify({'status': 'not found'}), 404



@app.route('/research')
def research():
    """Render the dashboard page."""
    return render_template('research.html')

@app.route('/faqs')
def faqs():
    """Render the FAQs page."""
    return render_template('faqs.html')
@app.route('/podcast')
def podcast():
    return render_template('podcast.html')
@app.route('/dashboard')
def dashboard():
    """Render the dashboard page."""
    return render_template('dashboard.html')
# ml analyzer
@app.route('/ml-analyzer', methods=['GET', 'POST'])
@login_required
def ml_analyzer():
    analysis_result = None
    chart_data = {}
    error = None

    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            error = "No file uploaded."
        else:
            try:
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                ext = os.path.splitext(filename)[1].lower()

                if ext == '.csv':
                    analysis_result, chart_data = analyzer_logic.analyze_csv(filepath)
                elif ext == '.docx':
                    analysis_result, chart_data = analyzer_logic.analyze_docx(filepath)
                elif ext == '.pdf':
                    analysis_result, chart_data = analyzer_logic.analyze_pdf(filepath)
                elif ext in ['.jpg', '.jpeg', '.png']:
                    analysis_result, chart_data = analyzer_logic.analyze_image_model_output(filepath, image_model)
                elif ext in ['.mp4', '.mov', '.avi']:
                    analysis_result, chart_data = analyzer_logic.analyze_video(filepath)
                else:
                    error = "Unsupported file type."

            except Exception as e:
                error = f"Error: {str(e)}"
    
    return render_template("ml_analyzer.html", 
                           analysis_result=analysis_result, 
                           chart_data=chart_data, 
                           error=error)
@app.route('/api/analyze_document', methods=['POST'])
@login_required
def analyze_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file_ext = filename.rsplit('.', 1)[1].lower()
    
    if analyzer_logic.allowed_file(filename):
        file.save(filepath)
        data_summary, text_content = analyzer_logic.analyze_document_data(filepath, file_ext)
        os.remove(filepath)
        if not data_summary:
            return jsonify({"error": "Could not process file"}), 500
        
        misinformation_result = analyzer_logic.analyze_document_misinformation(text_content)
        
        response = {
            "success": True,
            "document_analysis": {
                "misinformation_flag": "Misinformation detected" if misinformation_result["is_misinformation"] else "Data appears to be true",
                "misinformation_explanation": misinformation_result["explanation"],
                "data_summary": data_summary
            }
        }
        return jsonify(response)
    
    return jsonify({"error": "File type not allowed"}), 400

@app.route('/api/analyze_image', methods=['POST'])
@login_required
def analyze_image():
    if 'file' not in request.files:
        return jsonify({"error": "No image file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected image file"}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    if analyzer_logic.allowed_file(filename):
        file.save(filepath)
        
        # Pass the image model to the analysis function
        analysis_results = analyzer_logic.analyze_image_model_output(filepath, image_model)
        
        # Save the diagnostic result to the database
        first_detection = analysis_results['detections'][0]
        diagnosis_name = first_detection['label']
        diagnosis_type = "plant" if "maize" in diagnosis_name.lower() or "armyworm" in diagnosis_name.lower() else "animal"
        cause = first_detection['details'].split('\n')[1].replace('Cause: ', '').strip()
        treatment = first_detection['details'].split('\n')[2].replace('Treatment: ', '').strip()
        
        # In a production app, save to cloud storage and use the public URL
        # For this example, we use the local path.
        image_url = f"/uploads/{filename}"

        models.add_diagnostic_result(
            user_id=current_user.id,
            image_url=image_url,
            diagnosis_name=diagnosis_name,
            diagnosis_type=diagnosis_type,
            cause=cause,
            treatment=treatment,
            confidence_score=first_detection.get('confidence', None)
        )
        
        return jsonify(analysis_results)

    return jsonify({"error": "Image file type not allowed"}), 400

# --- New Routes for Community Notes and Diagnostics ---
@app.route('/api/diagnostics', methods=['GET'])
@login_required
def get_diagnostics():
    user_diagnostics = models.DiagnosticResult.query.filter_by(user_id=current_user.id).order_by(models.DiagnosticResult.created_at.desc()).all()
    
    results = []
    for diag in user_diagnostics:
        results.append({
            'id': diag.id,
            'diagnosis_name': diag.diagnosis_name,
            'image_url': diag.image_url,
            'confidence': diag.confidence_score,
            'created_at': diag.created_at.isoformat()
        })
        
    return jsonify({"success": True, "diagnostics": results})

# --- USSD Simulation ---
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

# --- USSD Simulation ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ussd_logs.db'

class USSDLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code_entered = db.Column(db.String(50))
    response_given = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Manually ensure tables are created
with app.app_context():
    db.create_all()


@app.route('/ussd', methods=['GET', 'POST'])
def ussd():
    response = None
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

    if request.method == 'POST':
        ussd_code = request.form.get('ussd_code', '').strip()
        session_level = request.form.get('session_level', '')

        if ussd_code == '*456#' and session_level == '':
            response = menu
            session_level = 'main_menu'

        elif session_level == 'main_menu':
            responses = {
                '1': "☀ Weather Today: Sunny, 28°C",
                '2': "🗻 Altitude at your location: 1,450 meters",
                '3': "🌱 Soil Type: Loamy",
                '4': "🐛 Pest Alert: Fall Armyworm in maize.",
                '5': "💰 Maize: KES 45/kg, Beans: KES 80/kg",
                '6': "🛒 Nearest Market: Machakos Open Market",
                '7': "🧠 Tip: Rotate crops to improve soil fertility.",
                '8': "💡 Innovation: AI-Powered Irrigation in Nairobi.",
                '9': "🚫 Fake: 'Boiling seeds increases yield' is FALSE.",
                '10': "👋 Thanks for using AgriTrue. Goodbye!"
            }
            response = responses.get(ussd_code, "❌ Invalid option. Try again.")
            session_level = ''

        else:
            response = "Enter *456# to begin."

        log = USSDLog(code_entered=ussd_code, response_given=response)
        db.session.add(log)
        db.session.commit()

        return render_template('ussd.html', response=response, session_level=session_level)

    return render_template('ussd.html', response=None, session_level='')
#chatbot
from flask import Flask, request, jsonify, render_template
import openai
import os
import speech_recognition as sr
from werkzeug.utils import secure_filename
from twilio.twiml.messaging_response import MessagingResponse
from collections import defaultdict
from flask_sqlalchemy import SQLAlchemy
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

openai.api_key = 'YOUR_OPENAI_API_KEYsk-proj-Y4GnL1d-hQ1--Fz4_2C9Pj45UHob9nfXC3sHelv8e4XzQgv59JdCYN7WqL1XCLXVRyx6DX6ij3T3BlbkFJ0hwnR8PmHUPkaT_Ote-FEIANgmQucoUqfpJ54qRBUET2ezOzF935kcrs_xOX5T5nxbyKL-qQcA'

# Render chatbot HTML page
@app.route('/chatbot', methods=['GET'])
def chatbot_page():
    return render_template('chatbot.html')

# Handle chatbot POST request
@app.route('/chatbot', methods=['POST'])
def chatbot_reply():
    user_input = request.json.get('user_input')
    if user_input:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=user_input,
            max_tokens=150
        )
        return jsonify({'response': response.choices[0].text.strip()})
    return jsonify({'response': 'No input received'})

# Handle voice file upload and transcription
@app.route('/chatbot/voice', methods=['POST'])
def voice_chatbot():
    audio = request.files['audio']
    filename = secure_filename(audio.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    audio.save(path)

    recognizer = sr.Recognizer()
    with sr.AudioFile(path) as source:
        audio_data = recognizer.record(source)
        try:
            user_input = recognizer.recognize_google(audio_data)
            response = openai.Completion.create(
                engine="text-davinci-003",
                prompt=user_input,
                max_tokens=150
            )
            return jsonify({'response': response.choices[0].text.strip()})
        except Exception as e:
            return jsonify({'response': f"Error: {str(e)}"})

# WhatsApp support (optional)
@app.route('/whatsapp', methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.form.get('Body')
    resp = MessagingResponse()
    msg = resp.message()
    response = generate_bot_response(incoming_msg)
    msg.body(response)
    return str(resp)

def generate_bot_response(user_input):
    res = openai.Completion.create(
        engine="text-davinci-003",
        prompt=user_input,
        max_tokens=150
    )
    return res.choices[0].text.strip()




# Mock agricultural data by county
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

@app.route('/know_your_land', methods=['GET', 'POST'])
@login_required
def know_your_land():
    results = {}
    if request.method == 'POST':
        county = request.form['county'].strip().lower()
        results = mock_data.get(county, {})
    return render_template('know_your_land.html', results=results)

#streak
# streak_backend_flask.py


# The updated profile route
@app.route('/profile')
@login_required
def profile():
    """
    Renders the user's profile page.

    The @login_required decorator ensures only authenticated users
    can access this page. The current_user object is automatically
    provided by Flask-Login and contains the user's information.
    """
    return render_template('profile.html', user=current_user)

# This route handles both displaying the profile edit form (GET) and processing
# the form submission (POST).
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        flash('Please log in to edit your profile.')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found.')
        return redirect(url_for('login'))

    # If the request method is POST, it means the user has submitted the form.
    if request.method == 'POST':
        # Retrieve all form data from the request.
        new_username = request.form.get('username')
        new_fullname = request.form.get('fullname')
        new_email = request.form.get('email')
        new_phone = request.form.get('phone')
        new_country = request.form.get('country')
        new_password = request.form.get('password')

        # Check for username uniqueness if it has changed.
        # This prevents another user from taking the current user's username.
        if new_username and new_username != user.username:
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user:
                flash('Username already taken. Please choose another one.')
                return redirect(url_for('edit_profile'))
            user.username = new_username

        # Update other profile fields with the submitted data.
        user.fullname = new_fullname
        user.email = new_email
        user.phone = new_phone
        user.country = new_country
        
        # Handle password change securely.
        # The password field is optional, so we only update it if a new value is provided.
        if new_password:
            user.password_hash = generate_password_hash(new_password)

        try:
            db.session.commit()
            flash('Profile updated successfully!')
        except Exception as e:
            db.session.rollback()
            flash(f'An error occurred: {e}')

        # Redirect to the main profile page after a successful update.
        return redirect(url_for('profile'))

    # If the request method is GET, just render the template with the current user's data.
    return render_template('edit_profile.html', user=user)

# Route for handling avatar uploads.
# This remains a separate function as it's a distinct task.
@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    """Handles the upload of a new user avatar."""
    if 'user_id' not in session:
        flash('Please log in to upload an avatar.')
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        flash('User not found.')
        return redirect(url_for('login'))
    
    if 'avatar' not in request.files:
        flash('No file part.')
        return redirect(url_for('edit_profile'))

    file = request.files['avatar']

    if file.filename == '':
        flash('No selected file.')
        return redirect(url_for('edit_profile'))

    if file and allowed_file(file.filename):
        # Create the avatars directory if it doesn't exist.
        upload_folder = current_app.config['UPLOAD_FOLDER']
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        filename = secure_filename(file.filename)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        # Update the user's avatar URL in the database.
        user.avatar_url = url_for('static', filename=f'avatars/{filename}')
        db.session.commit()

        flash('Avatar uploaded successfully!')
    else:
        flash('Invalid file type. Allowed types: png, jpg, jpeg, gif.')
        
    return redirect(url_for('edit_profile'))
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))
# --- Main Run ---
# --- Main streak route for logged-in users and public profiles ---
@app.route('/streak')
@app.route('/streak/<username>')
def streak(username=None):
    """
    Displays the user's streak page.
    If a username is provided in the URL, it shows that user's public profile.
    Otherwise, it shows the logged-in user's profile.
    """
    if username:
        # Public view: Try to find the user by username
        user_to_show = User.query.filter_by(username=username).first()
        if not user_to_show:
            flash("Sorry, that user does not exist.", "error")
            return redirect(url_for('index')) # Redirect to a home page or error page
    else:
        # Private view: Check if a user is logged in
        if not current_user.is_authenticated:
            flash("You must be logged in to view your profile.", "info")
            return redirect(url_for('login'))
        user_to_show = current_user

    return render_template('streak.html', user=user_to_show)
# ----------------- ADMIN ROUTES -----------------

from flask import request

@app.route('/admin')
@login_required
def admin_dashboard():
    # Ensure only admin users can access
    if not current_user.is_admin:
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('dashboard'))
    
    # Fetch all users, notes, diagnostics, and comments
    users = User.query.order_by(User.created_at.desc()).all()
    notes = CommunityNote.query.order_by(CommunityNote.created_at.desc()).all()
    diagnostics = DiagnosticResult.query.order_by(DiagnosticResult.created_at.desc()).all()
    comments = Comment.query.order_by(Comment.created_at.desc()).all()

    # Calculate totals for dashboard cards
    total_users = len(users)
    total_notes = len(notes)
    total_diagnostics = len(diagnostics)
    total_comments = len(comments)

    return render_template(
        'admin_dashboard.html',
        users=users,
        notes=notes,
        diagnostics=diagnostics,
        comments=comments,
        total_users=total_users,
        total_notes=total_notes,
        total_diagnostics=total_diagnostics,
        total_comments=total_comments
    )


@app.route('/admin/delete_user/<string:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    # Ensure only admin users can delete
    if not current_user.is_admin:
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_note/<int:note_id>', methods=['POST'])
@login_required
def delete_note_admin(note_id):
    # Ensure only admin users can delete any note
    if not current_user.is_admin:
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('dashboard'))
    
    note = CommunityNote.query.get_or_404(note_id)
    try:
        db.session.delete(note)
        db.session.commit()
        flash('Note deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting note: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_diagnostic/<int:diagnostic_id>', methods=['POST'])
@login_required
def delete_diagnostic_admin(diagnostic_id):
    # Ensure only admin users can delete diagnostics
    if not current_user.is_admin:
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('dashboard'))
    
    diag = DiagnosticResult.query.get_or_404(diagnostic_id)
    try:
        db.session.delete(diag)
        db.session.commit()
        flash('Diagnostic deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting diagnostic: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment_admin(comment_id):
    # Ensure only admin users can delete comments
    if not current_user.is_admin:
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('dashboard'))
    
    comment = Comment.query.get_or_404(comment_id)
    try:
        db.session.delete(comment)
        db.session.commit()
        flash('Comment deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting comment: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))
@app.route('/log_analysis', methods=['POST'])
def log_analysis():
    data = request.get_json()

    # Map incoming data to DiagnosticResult fields
    diagnostic = DiagnosticResult(
        user_id=data['user_id'],
        image_url=data.get('filename', ''),           # URL or file path
        diagnosis_name=data.get('summary', 'Unknown'), # Use summary as diagnosis_name if no specific name
        diagnosis_type=data.get('type', 'unknown'),    # e.g., 'plant' or 'animal'
        cause=data.get('cause', 'N/A'),
        treatment=data.get('treatment', 'N/A'),
        confidence_score=data.get('confidence_score'),
        created_at=datetime.utcnow()
    )

    db.session.add(diagnostic)
    db.session.commit()
    return jsonify({'status':'success'})
@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user_admin(user_id):
    # Ensure only admin users can delete any user
    if not current_user.is_admin:
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(user_id)
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {e}', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/donate')
def donate():
    return render_template('donate.html')

if __name__ == '__main__':
   
    app.run(debug=True)
