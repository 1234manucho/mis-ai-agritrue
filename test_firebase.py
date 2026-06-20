import firebase_admin
from firebase_admin import credentials, auth

cred = credentials.Certificate("C:/Users/HomePC/Desktop/TAI CHILLS/mis-ai-agritrue/isaaa/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
print("Firebase Admin SDK initialized successfully")

try:
    user = auth.get_user_by_email("info@agritrue.org")
    print("User exists:", user.uid)
except auth.UserNotFoundError:
    print("User not found, can create new admin")
