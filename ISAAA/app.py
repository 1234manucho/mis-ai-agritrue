from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from flask_migrate import Migrate
import os
import re
import requests
import json
import uuid
from datetime import datetime, timedelta
from sqlalchemy import desc

# Firebase Admin
import firebase_admin
from firebase_admin import credentials, auth, firestore

# Local imports
from extensions import db
from models import CommunityNote, Comment, User, get_user, get_user_by_id, add_user, get_user_by_email

# Database
from flask_sqlalchemy import SQLAlchemy
import firebase_admin
# Google Generative AI
import google.generativeai as genai
genai.configure(api_key="AIzaSyAtHy3rOfV2aYRfi0Ywbt_RLQnQjN2dNrA")
model = genai.GenerativeModel('gemini-1.5-flash')

# OpenAI
import openai
openai.api_key = "your_openai_api_key"

# --- App Configuration ---
app = Flask(__name__)
CORS(app)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'uploads/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Flask-Login Initialization ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- SQLAlchemy Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agritrue.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)            # ✅ use db from extensions.py
migrate = Migrate(app, db)  # ✅ attach Flask-Migrate

# Create tables if not exist
with app.app_context():
    db.create_all()
# --- Firebase Initialization ---
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("firebase-service-account.json")
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized successfully.")
    except Exception as e:
        print(f"Error initializing Firebase Admin SDK: {e}")

# Firestore client
firestore_db = firestore.client()
FIREBASE_API_KEY = "AIzaSyA_Ku2Qo_tul9Xr61NwVszfr6h92LZC53U"

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    """
    Flask-Login hook to reload the user object from the session.
    Uses Firebase UID as the lookup key in the local SQLAlchemy DB.
    """
    return User.query.get(user_id)


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


# --- Login Route ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login using Firebase REST API for password authentication."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return redirect(url_for('login'))

        try:
            # Firebase REST API for signInWithPassword
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
            payload = {"email": email, "password": password, "returnSecureToken": True}
            res = requests.post(url, data=payload)
            res_data = res.json()

            if "error" in res_data:
                flash("Invalid email or password.", "error")
                return redirect(url_for('login'))

            uid = res_data["localId"]

            # Firestore User Data
            user_ref = firestore_db.collection("users").document(uid)
            user_doc = user_ref.get()
            if not user_doc.exists:
                flash("User profile missing. Contact support.", "error")
                return redirect(url_for('login'))

            user_data = user_doc.to_dict()

            # --- Streak Update ---
            today = datetime.utcnow().date()
            streak = user_data.get("streak_count", 1)
            last_login = user_data.get("last_login")

            last_login_date = datetime.fromisoformat(last_login).date() if isinstance(last_login, str) else last_login.date()

            if last_login_date == today - timedelta(days=1):
                streak += 1
            elif last_login_date < today - timedelta(days=1):
                streak = 1

            user_ref.update({
                "streak_count": streak,
                "last_login": datetime.utcnow().isoformat()
            })

            # --- Local DB Sync ---
            user = db.session.get(User, uid)   # ✅ fixed for SQLAlchemy 2.0
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
                    created_at=datetime.fromisoformat(user_data.get('created_at'))
                )
                db.session.add(user)
                db.session.commit()

            login_user(user)

            flash(f"✅ Logged in! Current streak: {streak} days.", "success")
            return redirect(url_for('home'))

        except Exception as e:
            flash(f"⚠️ Login failed: {str(e)}", "error")
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



#dashboard
from flask import render_template, jsonify
from collections import defaultdict
import sqlite3

DB_NAME = "agritrue"  # Make sure this is set to your DB file

@app.route('/dashboard')
def dashboard():
    """Render the dashboard page."""
    return render_template('dashboard.html')


def fetch_chart_data():
    """Fetch and organize all chart datasets from the database."""
    charts = {}

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.cursor()

            # Soil data by county
            cur.execute("""
                SELECT county, soil_type, COUNT(*) 
                FROM soil_data 
                GROUP BY county, soil_type
            """)
            soil_data = defaultdict(list)
            for county, soil_type, count in cur.fetchall():
                soil_data[county].append({'soil_type': soil_type, 'count': count})
            charts['soil_by_county'] = dict(soil_data)

            # Pests by region
            cur.execute("""
                SELECT region, pest_type, COUNT(*) 
                FROM pest_reports 
                GROUP BY region, pest_type
            """)
            pest_data = defaultdict(list)
            for region, pest_type, count in cur.fetchall():
                pest_data[region].append({'pest_type': pest_type, 'count': count})
            charts['pests_by_region'] = dict(pest_data)

            # Innovations by county
            cur.execute("""
                SELECT county, innovation, COUNT(*) 
                FROM innovations 
                GROUP BY county, innovation
            """)
            innovation_data = defaultdict(list)
            for county, innovation, count in cur.fetchall():
                innovation_data[county].append({'innovation': innovation, 'count': count})
            charts['innovations_by_county'] = dict(innovation_data)

            # Weather data
            cur.execute("""
                SELECT county, weather_type, value 
                FROM weather_data
            """)
            weather_data = defaultdict(list)
            for county, weather_type, value in cur.fetchall():
                weather_data[county].append({'weather_type': weather_type, 'value': value})
            charts['weather_by_county'] = dict(weather_data)

            # Altitude data
            cur.execute("""
                SELECT county, altitude 
                FROM altitude_data
            """)
            altitude_data = defaultdict(list)
            for county, altitude in cur.fetchall():
                altitude_data[county].append({'altitude': altitude})
            charts['altitude_by_county'] = dict(altitude_data)

            # Weed types
            cur.execute("""
                SELECT county, weed_type 
                FROM weed_types
            """)
            weed_data = defaultdict(list)
            for county, weed_type in cur.fetchall():
                weed_data[county].append({'weed_type': weed_type})
            charts['weeds_by_county'] = dict(weed_data)

    except sqlite3.Error as e:
        charts['error'] = f"Database error: {str(e)}"
    except Exception as e:
        charts['error'] = f"Unexpected error: {str(e)}"

    return charts


@app.route('/api/chart-data')
def chart_data():
    """API endpoint to return all chart data as JSON."""
    return jsonify(fetch_chart_data())

from flask import Flask, render_template, request
from werkzeug.utils import secure_filename
import os
import pandas as pd
from docx import Document
import fitz  # PyMuPDF for PDF
from PIL import Image
import cv2



# Correct upload path (consistent with HTML/static use)
app.config['UPLOAD_FOLDER'] = 'static/avatars'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# CSV Analysis
def analyze_csv(filepath):
    df = pd.read_csv(filepath)
    summary = df.describe(include='all').to_dict()
    charts = {}

    for col in df.select_dtypes(include=['object', 'category']).columns[:5]:
        charts[col] = df[col].value_counts().head(10).to_dict()

    for col in df.select_dtypes(include=['number']).columns[:5]:
        charts[col] = {
            'min': df[col].min(),
            'max': df[col].max(),
            'mean': df[col].mean(),
            'median': df[col].median()
        }

    return summary, charts

# DOCX Analysis
def analyze_docx(filepath):
    doc = Document(filepath)
    text = "\n".join([para.text for para in doc.paragraphs])
    return {'Text': {'Content': text[:1000]}}, {}

# PDF Analysis
def analyze_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    for page in doc:
        text += page.get_text()
    return {'Text': {'Content': text[:1000]}}, {}

# Image Analysis
def analyze_image(filepath):
    img = Image.open(filepath)
    return {'Image': {'Size': img.size, 'Format': img.format}}, {}

# Video Analysis
def analyze_video(filepath):
    cap = cv2.VideoCapture(filepath)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return {'Video': {'Frame Count': frame_count}}, {}

# Analyzer Route
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
                    analysis_result, chart_data = analyze_csv(filepath)
                elif ext == '.docx':
                    analysis_result, chart_data = analyze_docx(filepath)
                elif ext == '.pdf':
                    analysis_result, chart_data = analyze_pdf(filepath)
                elif ext in ['.jpg', '.jpeg', '.png']:
                    analysis_result, chart_data = analyze_image(filepath)
                elif ext in ['.mp4', '.mov', '.avi']:
                    analysis_result, chart_data = analyze_video(filepath)
                else:
                    error = "Unsupported file type."

            except Exception as e:
                error = f"Error: {str(e)}"

    return render_template("ml_analyzer.html",
                           analysis_result=analysis_result,
                           chart_data=chart_data,
                           error=error)
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
if __name__ == '__main__':
   
    app.run(debug=True)
