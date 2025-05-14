from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import os
import sqlite3
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import openai
import speech_recognition as sr
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from collections import defaultdict
import pandas as pd

from flask import Flask, render_template, request
from flask_cors import CORS


# --- Configuration ---
app = Flask(__name__)
CORS(app)
app.secret_key = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'uploads/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

openai.api_key = "your_openai_api_key"

# --- Flask-Login Setup ---
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def init(self, id, username, is_admin):
        self.id = id
        self.username = username
        self.is_admin = bool(is_admin)

@login_manager.user_loader
def load_user(user_id):
    row = get_user_by_id(int(user_id))
    if row:
        uid, uname, _pw, is_admin = row
        return User(uid, uname, is_admin)
    return None

# --- Database Functions ---
DB_NAME = "agritrue.db"

def query_db(query, args=(), one=False):
    with sqlite3.connect(DB_NAME) as con:
        cur = con.cursor()
        cur.execute(query, args)
        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        
        cur.execute("""CREATE TABLE IF NOT EXISTS community_notes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        note TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        tags TEXT, verified INTEGER DEFAULT 0, reposted_from INTEGER, upvotes INTEGER DEFAULT 0);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS comments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        note_id INTEGER, FOREIGN KEY(note_id) REFERENCES community_notes(id));""")
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE, password TEXT, is_admin INTEGER DEFAULT 0);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS soil_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        county TEXT, soil_type TEXT);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS pest_reports (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        region TEXT, pest_type TEXT);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS innovations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        county TEXT, innovation TEXT);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS weather_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        county TEXT, weather_type TEXT, value INTEGER);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS altitude_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        county TEXT, altitude INTEGER);""")
        cur.execute("""CREATE TABLE IF NOT EXISTS weed_types (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        county TEXT, weed_type TEXT);""")

        # Insert sample data if empty
        cur.execute("SELECT COUNT(*) FROM soil_data")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO soil_data (county, soil_type) VALUES (?, ?)", [
                ('Nairobi', 'Clay'), ('Nairobi', 'Clay'), ('Kisumu', 'Sandy'), ('Kisumu', 'Loam')
            ])
        cur.execute("SELECT COUNT(*) FROM pest_reports")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO pest_reports (region, pest_type) VALUES (?, ?)", [
                ('Western', 'Armyworm'), ('Western', 'Armyworm'), ('Rift Valley', 'Locust')
            ])
        cur.execute("SELECT COUNT(*) FROM innovations")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO innovations (county, innovation) VALUES (?, ?)", [
                ('Nairobi', 'Biotech'), ('Kisumu', 'Drone Spraying'), ('Kisumu', 'Biotech')
            ])

        conn.commit()

def save_note(note, tags=None, reposted_from=None):
    query_db("INSERT INTO community_notes (note, tags, reposted_from) VALUES (?, ?, ?)", (note, tags, reposted_from))

def get_all_notes():
    return query_db("SELECT id, note, timestamp, verified, tags, upvotes FROM community_notes ORDER BY timestamp DESC")

def add_comment(note_id, content):
    query_db("INSERT INTO comments (note_id, content) VALUES (?, ?)", (note_id, content))

def get_comments_for_note(note_id):
    return query_db("SELECT content, timestamp FROM comments WHERE note_id=? ORDER BY timestamp", (note_id,))

def verify_note(note_id):
    query_db("UPDATE community_notes SET verified=1 WHERE id=?", (note_id,))

def upvote_note(note_id):
    query_db("UPDATE community_notes SET upvotes = upvotes + 1 WHERE id=?", (note_id,))

def add_user(username, pw_hash, is_admin=0):
    query_db("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)", (username, pw_hash, is_admin))

def get_user(username):
    return query_db("SELECT id, username, password, is_admin FROM users WHERE username=?", (username,), one=True)

def get_user_by_id(user_id):
    return query_db("SELECT id, username, password, is_admin FROM users WHERE id=?", (user_id,), one=True)

# --- Twilio Config ---
TWILIO_PHONE_NUMBER = 'whatsapp:+14155238886'
TWILIO_SID = 'your_twilio_sid'
TWILIO_AUTH_TOKEN = 'your_twilio_auth_token'
client = Client(TWILIO_SID, TWILIO_AUTH_TOKEN)

def send_whatsapp_message(to, message):
    client.messages.create(body=message, from_=TWILIO_PHONE_NUMBER, to=f'whatsapp:{to}')

# --- Routes ---
@app.route('/')
def home():
    return render_template('home.html')
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.security import generate_password_hash
import sqlite3



# --- User Registration and Login ---
# Initialize the database
def init_db():
    with sqlite3.connect("users.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                email TEXT,
                fullname TEXT
            )
        """)
init_db()

# Get a user by username
def get_user(username):
    with sqlite3.connect("users.db") as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        return cur.fetchone()

# Add a new user
def add_user(username, password, email, fullname):
    with sqlite3.connect("users.db") as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password, email, fullname) VALUES (?, ?, ?, ?)",
            (username, password, email, fullname)
        )
        conn.commit()

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        fullname = request.form['fullname']

        if get_user(username):
            error = "Username already exists"
        else:
            hashed_pw = generate_password_hash(password)
            add_user(username, hashed_pw, email, fullname)
            return redirect(url_for('login'))

    return render_template('register.html', error=error)

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = get_user(username)

        if user and check_password_hash(user[2], password):  # user[2] is the hashed password
            session['username'] = username
            return redirect(url_for('home'))  # Redirect to home page after successful login
        else:
            error = "Invalid username or password"

    return render_template('login.html', error=error)

# Logout route
@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))





@app.route('/community-notes', methods=['GET', 'POST'])
def community_notes():
    if request.method == 'POST':
        note = request.form.get('note')
        tags = request.form.get('tags')
        if note:
            save_note(note, tags)
    notes = get_all_notes()
    enriched = []
    for n in notes:
        note_id, content, ts, verified, tags, upvotes = n
        comments = get_comments_for_note(note_id)
        enriched.append({"id": note_id, "content": content, "timestamp": ts, "verified": verified, "tags": tags, "upvotes": upvotes, "comments": comments})
    return render_template('community_notes.html', notes=enriched)

@app.route('/comment/<int:note_id>', methods=['POST'])
def post_comment(note_id):
    content = request.form.get('comment')
    if content:
        add_comment(note_id, content)
    return redirect(url_for('community_notes'))

@app.route('/verify/<int:note_id>', methods=['POST'])
def mark_verified(note_id):
    verify_note(note_id)
    return jsonify({'status': 'verified'})

@app.route('/upvote/<int:note_id>', methods=['POST'])
def upvote(note_id):
    upvote_note(note_id)
    return jsonify({'status': 'upvoted'})

@app.route('/repost/<int:note_id>', methods=['POST'])
def repost(note_id):
    note = next((n for n in get_all_notes() if n[0] == note_id), None)
    if note:
        save_note(note[1], note[4], reposted_from=note_id)
        return jsonify({'status': 'reposted'})
    return jsonify({'status': 'not found'}), 404

#dashboard

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

def fetch_chart_data():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    charts = {}

    cur.execute("SELECT county, soil_type, COUNT(*) FROM soil_data GROUP BY county, soil_type")
    soil_data = defaultdict(list)
    for county, soil, count in cur.fetchall():
        soil_data[county].append({'soil_type': soil, 'count': count})
    charts['soil_by_county'] = soil_data

    cur.execute("SELECT region, pest_type, COUNT(*) FROM pest_reports GROUP BY region, pest_type")
    pest_data = defaultdict(list)
    for region, pest, count in cur.fetchall():
        pest_data[region].append({'pest_type': pest, 'count': count})
    charts['pests_by_region'] = pest_data

    cur.execute("SELECT county, innovation, COUNT(*) FROM innovations GROUP BY county, innovation")
    innovation_data = defaultdict(list)
    for county, innov, count in cur.fetchall():
        innovation_data[county].append({'innovation': innov, 'count': count})
    charts['innovations_by_county'] = innovation_data

    # Fetch weather data
    cur.execute("SELECT county, weather_type, value FROM weather_data")
    weather_data = defaultdict(list)
    for county, weather_type, value in cur.fetchall():
        weather_data[county].append({'weather_type': weather_type, 'value': value})
    charts['weather_by_county'] = weather_data

    # Fetch altitude data
    cur.execute("SELECT county, altitude FROM altitude_data")
    altitude_data = defaultdict(list)
    for county, altitude in cur.fetchall():
        altitude_data[county].append({'altitude': altitude})
    charts['altitude_by_county'] = altitude_data

    # Fetch weed types data
    cur.execute("SELECT county, weed_type FROM weed_types")
    weed_data = defaultdict(list)
    for county, weed in cur.fetchall():
        weed_data[county].append({'weed_type': weed})
    charts['weeds_by_county'] = weed_data

    conn.close()
    return charts

@app.route('/api/chart-data')
def chart_data():
    return jsonify(fetch_chart_data())

from flask import Flask, render_template, request, redirect, url_for
import os
from werkzeug.utils import secure_filename
from PIL import Image
import pytesseract
import cv2
import numpy as np
import fitz  # PyMuPDF
import torch
from torchvision import models, transforms

# --- Machine Learning Analyzer ---
app.config['UPLOAD_FOLDER'] = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'mp4', 'mov', 'pdf'}

# Load image model
model = models.resnet50(pretrained=True)
model.eval()
transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor()
])
imagenet_classes = {idx: cls for (idx, cls) in enumerate(open("imagenet_classes.txt"))}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def analyze_image(path):
    image = Image.open(path).convert('RGB')
    img_tensor = transform(image).unsqueeze(0)
    with torch.no_grad():
        outputs = model(img_tensor)
    _, predicted = outputs.max(1)
    label = imagenet_classes[predicted.item()]
    return f"This image likely shows: {label.replace('_', ' ')}."

def analyze_video(path):
    cap = cv2.VideoCapture(path)
    success, frame = cap.read()
    cap.release()
    if success:
        temp_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_frame.jpg')
        cv2.imwrite(temp_image_path, frame)
        return analyze_image(temp_image_path)
    else:
        return "Could not analyze video frame."

def analyze_pdf(path):
    text = ""
    doc = fitz.open(path)
    for page in doc:
        text += page.get_text()
    return text.strip() or "No text found in PDF."

@app.route('/ml-analyzer', methods=['GET', 'POST'])
def ml_analyzer():
    if request.method == 'POST':
        if 'file' not in request.files:
            return render_template('ml_analyzer.html', error="No file uploaded.")
        file = request.files['file']
        if file.filename == '' or not allowed_file(file.filename):
            return render_template('ml_analyzer.html', error="Invalid file type.")

        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        ext = filename.rsplit('.', 1)[1].lower()
        result = ""
        file_type = ""

        try:
            if ext in ['jpg', 'jpeg', 'png']:
                file_type = 'image'
                result = analyze_image(save_path)
            elif ext in ['mp4', 'mov']:
                file_type = 'video'
                result = analyze_video(save_path)
            elif ext == 'pdf':
                file_type = 'pdf'
                result = analyze_pdf(save_path)
        except Exception as e:
            return render_template('ml_analyzer.html', error=str(e))

        return render_template('ml_analyzer.html', analysis_result=result, file_name=filename, file_type=file_type)

    return render_template('ml_analyzer.html')
#ussd 
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

# --- USSD Simulation ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ussd_db.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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
    1. pestiside verification<br>
    2. Verify my pesticides<br>
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
                '1': "check products at <a href='https://www.agritrue.com'>AgriTrue</a>",
                '2': "TYPE: Pesticide, NAME: Dudu Killer, STATUS: Verified",
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



@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    messages = data.get("messages", [])
    reply = generate_response(messages)
    return jsonify({"reply": reply})
def generate_response(messages):
    user_input = messages[-1]["content"].lower().strip()

    if "hello" in user_input:
        return "Hello Farmer! 😊"
    elif "how are you" in user_input:
        return "I'm doing great, thanks for asking!"
    elif "bye" in user_input:
        return "Goodbye! Talk to you soon."
    elif "help" in user_input:
        return "Sure! You can ask me about crops, weather, pests, farming tips, markets, and more."

    # Agricultural topics
    elif "muriena" in user_input:
        return "Muriena mno😙😚 wavolkho."
    elif "habari" in user_input:
        return "Jambo mkulima😊."
    elif "wheat" in user_input:
        return "Wheat is mostly grown in Nakuru, Uasin Gishu, and Trans Nzoia counties."
    elif "wheat" in user_input:
        return "Wheat is mostly grown in Nakuru, Uasin Gishu, and Trans Nzoia counties."
    elif "maize" in user_input:
        return "Maize is a staple crop in Kenya, often grown in Rift Valley and Western regions."
    elif "wheat" in user_input:
        return "Wheat is mostly grown in Nakuru, Uasin Gishu, and Trans Nzoia counties."
    elif "coffee" in user_input:
        return "Kenyan coffee is renowned globally. It's mainly grown in Central Kenya and parts of Rift Valley."
    elif "tea" in user_input:
        return "Kenya is one of the top tea exporters. Tea is largely grown in Kericho, Bomet, and Nyeri."
    elif "dairy" in user_input or "milk" in user_input:
        return "Dairy farming thrives in Central and Rift Valley regions. Cooling and feed management are key."
    elif "poultry" in user_input:
        return "Poultry farming includes layers and broilers. Proper vaccination is essential."
    elif "fish" in user_input or "aquaculture" in user_input:
        return "Aquaculture is growing around Lake Victoria and in Central Kenya through fish ponds."
    elif "irrigation" in user_input:
        return "Irrigation helps in arid zones like Turkana and parts of Machakos. Drip irrigation is efficient."
    elif "fertilizer" in user_input:
        return "Organic and inorganic fertilizers boost yield. Proper use depends on soil testing."
    elif "soil" in user_input:
        return "Soil testing is essential for crop selection. Black cotton soil suits cotton and maize well."
    elif "climate" in user_input or "weather" in user_input:
        return "Kenya has varied climates. Knowing your zone helps determine best planting seasons."
    elif "greenhouse" in user_input:
        return "Greenhouse farming extends growing seasons and protects crops from pests."
    elif "market" in user_input:
        return "You can access markets via cooperatives, digital platforms, or county market days."
    elif "prices" in user_input:
        return "Crop prices fluctuate. Check with the National Cereals Board or your nearest market."
    elif "subsidy" in user_input:
        return "Government subsidies are available for inputs like fertilizer and seeds."
    elif "weeds" in user_input:
        return "Common weeds like Striga and couch grass reduce yields. Use certified herbicides."
    elif "pests" in user_input:
        return "Fall armyworm affects maize; Tuta absoluta affects tomatoes. Use IPM techniques."
    elif "disease" in user_input:
        return "Crop diseases include blight in potatoes, rust in wheat, and bacterial wilt in tomatoes."
    elif "tractor" in user_input:
        return "Tractors improve efficiency. Hire services are available via government and private entities."
    elif "training" in user_input:
        return "You can attend farmer field schools or contact your county agricultural officer."
    elif "storage" in user_input:
        return "Proper storage reduces post-harvest losses. Use hermetic bags or metallic silos."
    elif "extension" in user_input:
        return "Agricultural extension services are provided by counties and NGOs."
    elif "youth" in user_input:
        return "Youth can access agri-funding through programs like Ajira, YEDF, and AgriBiz."
    elif "funding" in user_input:
        return "Try the Agricultural Finance Corporation (AFC), Equity Bank, or government grants."
    elif "agribusiness" in user_input:
        return "Agribusiness includes production, processing, and marketing. It offers job opportunities."
    elif "export" in user_input:
        return "Kenya exports tea, coffee, flowers, and fruits like mangoes and avocados."
    elif "livestock" in user_input:
        return "Livestock farming includes cattle, goats, sheep, and camels especially in ASAL areas."
    elif "goat" in user_input:
        return "Goat farming is common in Eastern and arid regions. It requires hardy breeds."
    elif "bees" in user_input or "apiculture" in user_input:
        return "Beekeeping produces honey and wax. Ensure proper hive management."
    else:
        return "I'm still learning! Try asking something else about crops, livestock, markets, or weather."
    




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






if __name__ == '__main__':
    init_db()
    app.run(debug=True)