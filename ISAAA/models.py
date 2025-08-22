from datetime import datetime
from flask_login import UserMixin
from extensions import db


# ===========================
# User Model
# ===========================
class User(db.Model, UserMixin):
    """
    SQLAlchemy model for the 'users' table.
    Stores local copy of user data linked to Firebase UID.
    """
    __tablename__ = 'users'   # ✅ plural is conventional

    # Firebase Authentication UID as the primary key
    id = db.Column(db.String(128), primary_key=True)

    # User details
    fullname = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    home_address = db.Column(db.String(200), nullable=True)
    country = db.Column(db.String(50), nullable=True)
    county = db.Column(db.String(50), nullable=True)

    # Firestore-synced fields
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    streak_count = db.Column(db.Integer, default=1)

    # 🔑 Password column (optional if Firebase handles auth)
    password = db.Column(db.String(200), nullable=True)

    # Relationships
    notes = db.relationship(
        "CommunityNote",
        back_populates="author",
        lazy=True,
        cascade="all, delete"
    )
    comments = db.relationship(
        "Comment",
        back_populates="author",
        lazy=True,
        cascade="all, delete"
    )

    def __repr__(self):
        return f"<User {self.username}>"


# ===========================
# Community Notes
# ===========================
class CommunityNote(db.Model):
    __tablename__ = 'communitynotes'

    id = db.Column(db.Integer, primary_key=True)
    note = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    upvotes = db.Column(db.Integer, default=0)
    verified = db.Column(db.Boolean, default=False)
    reposted_from = db.Column(db.Integer, nullable=True)

    # FK to users.id (Firebase UID)
    user_id = db.Column(db.String(128), db.ForeignKey('users.id'), nullable=False)

    # ✅ Relationships
    author = db.relationship("User", back_populates="notes")
    comments = db.relationship(
        "Comment",
        back_populates="parent_note",
        lazy=True,
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<CommunityNote {self.id} - {self.note[:20]}>"

    @staticmethod
    def create(note_text, tags, user_id):
        note = CommunityNote(note=note_text, tags=tags, user_id=user_id)
        db.session.add(note)
        db.session.commit()
        return note


# ===========================
# Comments
# ===========================
class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey('communitynotes.id'), nullable=False)
    user_id = db.Column(db.String(128), db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ Relationships (no duplicate backref names)
    parent_note = db.relationship("CommunityNote", back_populates="comments")
    author = db.relationship("User", back_populates="comments")

    def __repr__(self):
        return f"<Comment {self.id} by User {self.user_id}>"

    @staticmethod
    def create(note_id, user_id, text):
        try:
            comment = Comment(note_id=note_id, user_id=user_id, text=text)
            db.session.add(comment)
            db.session.commit()
            return comment
        except Exception as e:
            db.session.rollback()
            raise e


# ===========================
# Helper Functions
# ===========================
def add_user(uid, username, password=None, email=None, fullname=None):
    """Create a new user in the local database with Firebase UID."""
    user = User(
        id=uid,
        username=username,
        email=email,
        fullname=fullname
    )
    if password:  # Optional, since Firebase handles auth
        setattr(user, "password", password)

    db.session.add(user)
    db.session.commit()
    return user


def get_user_by_id(user_id):
    """Fetch a user by Firebase UID."""
    return db.session.get(User, user_id)


def get_user(username):
    """Fetch a user by username."""
    return db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()


def get_user_by_email(email):
    """Fetch a user by email."""
    return db.session.execute(
        db.select(User).filter_by(email=email)
    ).scalar_one_or_none()



# ===========================
# Diagnostic Results
# ===========================
class DiagnosticResult(db.Model):
    __tablename__ = 'diagnostics'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(128), db.ForeignKey('users.id'), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    diagnosis_name = db.Column(db.String(100), nullable=False)
    diagnosis_type = db.Column(db.String(50), nullable=False)  # 'plant', 'animal'
    cause = db.Column(db.Text, nullable=False)
    treatment = db.Column(db.Text, nullable=False)
    confidence_score = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    user = db.relationship("User", back_populates="diagnostics")

    def __repr__(self):
        return f"<DiagnosticResult {self.id} - {self.diagnosis_name}>"


# ===========================
# Helper Functions
# ===========================
def get_diagnostic_results(user_id):
    """
    Fetch all diagnostic results for a given user.
    """
    return db.session.execute(
        db.select(DiagnosticResult).filter_by(user_id=user_id)
    ).scalars().all()
def add_diagnostic_result(user_id, image_url, diagnosis_name, diagnosis_type, cause, treatment, confidence_score):
    """
    Adds a new diagnostic result to the database.
    """
    try:
        new_result = DiagnosticResult(
            user_id=user_id,
            image_url=image_url,
            diagnosis_name=diagnosis_name,
            diagnosis_type=diagnosis_type,
            cause=cause,
            treatment=treatment,
            confidence_score=confidence_score
        )
        db.session.add(new_result)
        db.session.commit()
        return new_result
    except Exception as e:
        db.session.rollback()
        raise e
