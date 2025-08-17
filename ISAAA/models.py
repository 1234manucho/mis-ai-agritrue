from extensions import db
from flask_login import UserMixin

from datetime import datetime
from flask_login import UserMixin, current_user
from extensions import db
class User(db.Model, UserMixin):
    __tablename__ = "users"

    # --- Core Fields ---
    id = db.Column(db.String(100), primary_key=True) 
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True) 
    email = db.Column(db.String(120), unique=True, nullable=False)
    fullname = db.Column(db.String(200), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    home_address = db.Column(db.String(300), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    county = db.Column(db.String(100), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- Constructor method to fix the TypeError ---
    def __init__(self, id, username, email, fullname=None, phone=None, id_number=None, home_address=None, country=None, county=None, password=None):
        self.id = id
        self.username = username
        self.email = email
        self.fullname = fullname
        self.phone = phone
        self.id_number = id_number
        self.home_address = home_address
        self.country = country
        self.county = county
        self.password = password

    # --- Flask-Login integration ---
    def get_id(self):
        """Flask-Login requires returning a string ID (Firebase UID)."""
        return str(self.id)

    def __repr__(self):
        return f"<User {self.username}>"

    # --- Utilities ---
    @staticmethod
    def get_current_user_id():
        """Return the currently logged-in user’s ID as string (or None)."""
        return current_user.id if current_user.is_authenticated else None

    def to_dict(self):
        """Serialize User model into dictionary format."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "fullname": self.fullname,
            "phone": self.phone,
            "id_number": self.id_number,
            "home_address": self.home_address,
            "country": self.country,
            "county": self.county,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
class CommunityNote(db.Model):
    __tablename__ = 'communitynote'

    id = db.Column(db.Integer, primary_key=True)
    note = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    upvotes = db.Column(db.Integer, default=0)  # ✅ Added
    verified = db.Column(db.Boolean, default=False)  # ✅ Added
    reposted_from = db.Column(db.Integer, nullable=True)  # ✅ Added
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    comments = db.relationship(
        'Comment',
        backref='note',
        cascade='all, delete',
        lazy=True
    )

    def __repr__(self):
        return f"<CommunityNote {self.id} - {self.note[:20]}>"


    @staticmethod
    def create(note_text, tags, user_id):
        note = CommunityNote(note=note_text, tags=tags, user_id=user_id)
        db.session.add(note)
        db.session.commit()
        return note


class Comment(db.Model):
    __tablename__ = 'comment'

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey('communitynote.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def create(note_id, user_id, text):
        comment = Comment(note_id=note_id, user_id=user_id, text=text)
        db.session.add(comment)
        db.session.commit()
        return comment


# Helper functions
def get_user_by_id(user_id):
    return db.session.get(User, user_id)


def get_user(username):
    return db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()


def add_user(username, password, email=None, fullname=None):
    user = User(username=username, password=password, email=email, fullname=fullname)
    db.session.add(user)
    db.session.commit()
    return user


def get_user_by_email(email):
    return db.session.execute(
        db.select(User).filter_by(email=email)
    ).scalar_one_or_none()