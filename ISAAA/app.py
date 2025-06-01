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
from flask import Flask, render_template, redirect, url_for, request, session
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
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



#analyzer
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename
import os
import pandas as pd
from docx import Document
import fitz  # PyMuPDF
from PIL import Image
import cv2
import numpy as np



UPLOAD_FOLDER = 'static/avatars'
ALLOWED_EXTENSIONS = {'csv', 'pdf', 'docx', 'doc', 'jpg', 'jpeg', 'png', 'mp4', 'mov'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def analyze_csv(filepath):
    try:
        df = pd.read_csv(filepath)
        analysis_result = {}
        chart_data = {}

        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                analysis_result[col] = {
                    'mean': round(df[col].mean(), 2),
                    'min': df[col].min(),
                    'max': df[col].max(),
                    'std': round(df[col].std(), 2),
                    'missing': int(df[col].isna().sum())
                }
                chart_data[col] = {
                    'Mean': df[col].mean(),
                    'Min': df[col].min(),
                    'Max': df[col].max()
                }
            else:
                value_counts = df[col].value_counts().head(5)
                analysis_result[col] = {
                    'top_values': value_counts.to_dict(),
                    'unique': df[col].nunique(),
                    'missing': int(df[col].isna().sum())
                }
                chart_data[col] = value_counts.to_dict()

        return analysis_result, chart_data
    except Exception as e:
        print("CSV Analysis Error:", e)
        return None, None

@app.route('/')
def index():
    return render_template('ml_analyzer.html')

@app.route('/ml_analyzer', methods=['POST'])
def ml_analyzer():
    if 'file' not in request.files:
        return render_template('ml_analyzer.html', error="No file part in request")

    file = request.files['file']
    if file.filename == '':
        return render_template('ml_analyzer.html', error="No file selected")

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        if filename.lower().endswith('.csv'):
            analysis_result, chart_data = analyze_csv(filepath)
            if analysis_result:
                return render_template('ml_analyzer.html',
                                       analysis_result=analysis_result,
                                       chart_data=chart_data)
            else:
                return render_template('ml_analyzer.html', error="Failed to analyze CSV file")
        else:
            return render_template('ml_analyzer.html', error="File uploaded successfully (non-CSV), but no analysis done.")
    else:
        return render_template('ml_analyzer.html', error="Invalid file type")

#ussd
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ussd_db.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class USSDLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code_entered = db.Column(db.String(50))
    response_given = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

languages = {
    "1": "English",
    "2": "Kiswahili",
    "3": "Luhya",
    "4": "Gikuyu",
    "5": "Kisii"
}

translations = {
    "Welcome": {
        "English": "\U0001F44B Welcome to <strong>AgriTrue</strong><br>Please select your language:<br>",
        "Kiswahili": "\U0001F44B Karibu kwenye <strong>AgriTrue</strong><br>Chagua lugha yako:<br>",
        "Luhya": "\U0001F44B Wamukasa ku <strong>AgriTrue</strong><br>Chagula lulimi lwakho:<br>",
        "Gikuyu": "\U0001F44B Wîthamûhîrîrî wa <strong>AgriTrue</strong><br>Thaitha wîcagûrûrû lugha:<br>",
        "Kisii": "\U0001F44B Bwakire buya ku <strong>AgriTrue</strong><br>Chagura ririmi ryao:<br>"
    },
    "Exit": {
        "English": "\U0001F44B Thank you for using AgriTrue. Goodbye!",
        "Kiswahili": "\U0001F44B Asante kwa kutumia AgriTrue. Kwaheri!",
        "Luhya": "\U0001F44B Webale muno kukhukhonya AgriTrue. Khulayi!",
        "Gikuyu": "\U0001F44B Wîthamîrîrie AgriTrue. Wîgîe wega!",
        "Kisii": "\U0001F44B Asante kwa kutumia AgriTrue. Bwakire buya!"
    },
    "Main Menu": {
        "English": "<strong>AgriTrue SERVICES:</strong><br>1. Pest Control Assistance<br>2. Pesticide Verification<br>3. Soil & Crop Advisory<br>4. Crop Prices & Markets<br>5. Expert Help Desk<br>0. Exit",
        "Kiswahili": "<strong>HUDUMA ZA AgriTrue:</strong><br>1. Msaada wa Wadudu<br>2. Uhakiki wa Dawa<br>3. Ushauri wa Udongo & Mazao<br>4. Bei za Mazao<br>5. Huduma ya Wataalamu<br>0. Exit",
        "Luhya": "<strong>MAHUDUMU A AgriTrue:</strong><br>1. Kukhira Amaloba<br>2. Khwikinya Obulafu<br>3. Amachesi ku Sikwo & Amatunda<br>4. Amabele ga Amatunda<br>5. Khusaba Omusomi<br>0. Exit",
        "Gikuyu": "<strong>THIRIKWA CIA AgriTrue:</strong><br>1. Kũheo ithuũri na mĩrimũ<br>2. Kũmenyekanĩrĩrĩa mathirikari<br>3. Wĩtikirio wa thurũri na mbembe<br>4. Mũthithania wa bũrũri<br>5. Mũgĩkũyũ wa wĩtikirio<br>0. Exit",
        "Kisii": "<strong>NYAMOKO Y'OBULIMI AgriTrue:</strong><br>1. Obokonyi bw’abasari<br>2. Okobwita ebiwabo<br>3. Gusabati ebisika n’ebibagara<br>4. Emari y’ebibagara<br>5. Kobwita omosomi<br>0. Exit"
    }
}

@app.route('/ussd', methods=['GET', 'POST'])
def ussd():
    response = None
    session_level = ''
    selected_language = ''

    if request.method == 'POST':
        ussd_code = request.form.get('ussd_code', '').strip()
        session_level = request.form.get('session_level', '')
        selected_language = request.form.get('selected_language', '')

        # Default to English if not set
        if not selected_language:
            selected_language = 'English'

        if ussd_code == '*456#' and session_level == '':
            response = translations['Welcome'][selected_language] + \
                       "<br>".join([f"{k}. {v}" for k, v in languages.items()]) + "<br>0. Exit"
            session_level = 'language_selection'

        elif session_level == 'language_selection':
            if ussd_code == '0':
                response = translations['Exit'][selected_language]
                session_level = ''
            elif ussd_code in languages:
                selected_language = languages[ussd_code]
                response = translations['Main Menu'].get(selected_language, translations['Main Menu']['English'])
                session_level = 'main_menu'
            else:
                response = "❌ Invalid choice. Try again:<br>" + \
                           "<br>".join([f"{k}. {v}" for k, v in languages.items()]) + "<br>0. Exit"

        elif session_level == 'main_menu':
            if ussd_code == '1':
                pest_categories = {
                    "English": "SELECT PEST CATEGORY:<br>1. Insects/Caterpillars<br>2. Fungal Diseases<br>3. Weeds<br>4. Can't Identify Pest<br>#. Back<br>0. Exit",
                    "Kiswahili": "CHAGUA AINA YA WADUDU:<br>1. Wadudu/Vitunguu<br>2. Magonjwa ya Ukungu<br>3. Magugu<br>4. Siwezi Tambua Wadudu<br>#. Rudi<br>0. Exit",
                    "Luhya": "KHULA LUYENYI LW’EMISWA:<br>1. Insects/Obunyenya<br>2. Amibimbi<br>3. Amatunda<br>4. Sindinyala Khumanya<br>#. Rudi<br>0. Exit",
                    "Gikuyu": "HĨTĨRA MŨRIMŨ:<br>1. Ndurũ/Vithũmũ<br>2. Mĩrimũ ya Fungus<br>3. Magugu<br>4. Ndĩgĩtĩkĩrie mũrĩmũ<br>#. Gũcoka<br>0. Exit",
                    "Kisii": "RAGERA RIRIMI RI'OBOSARE:<br>1. Ensangwe/Nyegonyego<br>2. Chironda<br>3. Ebibiranya<br>4. Sindi chigwete<br>#. Rokera<br>0. Exit"
                }
                response = pest_categories[selected_language]
                session_level = 'pest_category'

            elif ussd_code == '2':
                response = {
                    "English": "ENTER PRODUCT NAME OR REGISTRATION NUMBER:<br>(e.g., 'Glyphosate 41% SL' or 'KEPHIS PX-12345')",
                    "Kiswahili": "ANDIKA JINA LA BIDHAA AU NAMBA YA USAJILI:<br>(kwa mfano: 'Glyphosate 41% SL' au 'KEPHIS PX-12345')",
                    "Luhya": "ANDIKA ERINYA LYA PRODUCT KUNDA YANGE ESIKHULU:<br>(okhukholola: 'Glyphosate 41% SL')",
                    "Gikuyu": "ANDIKA RĨTWA RĨA MATHIRIKARI KANA NĨMBA YA USAJIRI:<br>(rĩrĩa: 'Glyphosate 41% SL')",
                    "Kisii": "RANDA ZINA YA OBULIMI OKO REGISTRATION CODE:<br>(e.g. 'Glyphosate 41% SL')"
                }[selected_language]
                session_level = 'pesticide_input'

            elif ussd_code == '3':
                response = {
                    "English": "SELECT YOUR COUNTY:<br>1. Nakuru<br>2. Embu<br>...<br>47. Turkana<br>0. Exit",
                    "Kiswahili": "CHAGUA KAUNTI YAKO:<br>1. Nakuru<br>2. Embu<br>...<br>47. Turkana<br>0. Exit",
                    "Luhya": "KHULA KAUNTI YAKHO:<br>1. Nakuru<br>2. Embu<br>...<br>47. Turkana<br>0. Exit",
                    "Gikuyu": "THITHANIA KAUNTI YAKU:<br>1. Nakuru<br>2. Embu<br>...<br>47. Turkana<br>0. Exit",
                    "Kisii": "RAGERA COUNTY YAO:<br>1. Nakuru<br>2. Embu<br>...<br>47. Turkana<br>0. Exit"
                }[selected_language]
                session_level = 'soil_info'

            elif ussd_code == '4':
                response = {
                    "English": "SELECT CROP:<br>1. Maize<br>2. Tomatoes<br>...<br>8. Other Crops<br>0. Exit",
                    "Kiswahili": "CHAGUA MAZAO:<br>1. Mahindi<br>2. Nyanya<br>...<br>8. Mazao Mengine<br>0. Exit",
                    "Luhya": "KHULA AMATUNDA:<br>1. Obusuma<br>2. Omunyanya<br>...<br>8. Amatunda Ka<br>0. Exit",
                    "Gikuyu": "THITHANIA MBEMBE:<br>1. Mũgũmbĩ<br>2. Nyanya<br>...<br>8. Ĩgĩrĩria<br>0. Exit",
                    "Kisii": "RAGERA EBIKIO:<br>1. Oboka<br>2. Nyanya<br>...<br>8. Ebindi<br>0. Exit"
                }[selected_language]
                session_level = 'crop_prices'

            elif ussd_code == '5':
                response = {
                    "English": "CONTACT OPTIONS:<br>1. Call County Agent (Free)<br>2. WhatsApp Chat<br>3. Visit Office<br>0. Exit",
                    "Kiswahili": "CHAGUO ZA MAWASILIANO:<br>1. Piga Wakala (Bure)<br>2. WhatsApp Chat<br>3. Tembelea Ofisi<br>0. Exit",
                    "Luhya": "OKHUSABA OKHUBWA:<br>1. Khuchema Agent<br>2. WhatsApp<br>3. Okhulola Office<br>0. Exit",
                    "Gikuyu": "WIRA WA KUGÛCOKA:<br>1. Hoya mũtuhĩ<br>2. WhatsApp<br>3. Gũcoka Office<br>0. Exit",
                    "Kisii": "BORA ROKERA MOSOBOKI:<br>1. Bera Official<br>2. WhatsApp<br>3. Gokera Office<br>0. Exit"
                }[selected_language]
                session_level = 'expert_help'

            elif ussd_code == '0':
                response = translations['Exit'][selected_language]
                session_level = ''

            else:
                response = translations['Main Menu'][selected_language]

        # Handle other session levels as-is (pest_category, etc.) and translate content there too...

        log = USSDLog(code_entered=ussd_code, response_given=response)
        db.session.add(log)
        db.session.commit()

        return render_template('ussd.html', response=response,
                               session_level=session_level,
                               selected_language=selected_language)

    return render_template('ussd.html', response=None, session_level='', selected_language='')


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

#streak
# streak_backend_flask.py


# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)
    region = db.Column(db.String(100), default='Unknown')
    crops = db.Column(db.String(200), default='Maize, Beans')
    last_login = db.Column(db.DateTime)
    streak = db.Column(db.Integer, default=0)

# Login route with streak update
from flask import flash, redirect, render_template, url_for

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            # Update streak
            now = datetime.utcnow()
            if user.last_login:
                delta = (now.date() - user.last_login.date()).days
                if delta == 1:
                    user.streak += 1
                elif delta > 1:
                    user.streak = 1
            else:
                user.streak = 1

            user.last_login = now
            db.session.commit()

            login_user(user)
            flash('Logged in successfully!')
            return redirect(url_for('profile'))  # or 'home' depending on your app

        flash('Invalid username or password')

    return render_template('login.html')

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        fullname = request.form['fullname']
        if User.query.filter_by(username=username).first():
            return "Username already exists."

        new_user = User(username=username, password=password, streak=1, last_login=datetime.utcnow())
        db.session.add(new_user)
        db.session.commit()

        # Do NOT log in the user automatically. Redirect to login page.
        return redirect(url_for('login'))

    return render_template('register.html')

# Profile route
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    if not user:
        session.pop('user_id', None)
        return redirect(url_for('login'))

    # Pass user object to template
    return render_template('profile.html', user=user)

# Edit profile route
@app.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        new_username = request.form['username']

        # Check if the new username is taken by another user
        existing_user = User.query.filter_by(username=new_username).first()
        if existing_user and existing_user.id != user.id:
            flash('Username already taken. Please choose another one.')
            return redirect(url_for('edit_profile'))

        user.username = new_username
        user.region = request.form['region']
        user.crops = request.form['crops']
        db.session.commit()

        flash('Profile updated successfully.')
        return redirect(url_for('profile'))

    return render_template('edit_profile.html', user=user)

# Folder where uploaded avatars will be stored
UPLOAD_FOLDER = 'static/avatars'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 # 2MB limit

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Check if the file has an allowed extension
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Route for avatar upload
@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if 'avatar' not in request.files:
        flash('No file part')
        return redirect(url_for('edit_profile'))

    file = request.files['avatar']

    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('edit_profile'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Save avatar filename to user's profile
        user = User.query.get(session['user_id'])
        user.avatar = filename
        db.session.commit()

        flash('Avatar uploaded successfully!')
        return redirect(url_for('edit_profile'))

    flash('Invalid file type. Allowed types: png, jpg, jpeg, gif')
    return redirect(url_for('edit_profile'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))
# --- Main Run ---

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
