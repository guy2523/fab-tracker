# firebase_client.py
import pyrebase
import requests
import json

# ============================================
# 1. FIREBASE WEB CONFIG (FILL THIS IN)
# ============================================
firebaseConfig = {
    "apiKey": "AIzaSyC4ekPpnhhwNQU_w78-6NaeITIGe67gS8I",
    "authDomain": "fab-tracker-93819.firebaseapp.com",
    "projectId": "fab-tracker-93819",
    "storageBucket": "fab-tracker-93819.appspot.com",
  	"messagingSenderId": "516510758182",
  	"appId": "1:516510758182:web:a632746532b9d49f5a3de7",
    "databaseURL": "https://fab-tracker-93819.firebaseio.com"  # Pyrebase requires this key even if empty
}

# ============================================
# 2. AUTHENTICATION (Pyrebase)
# ============================================
try:
    firebase = pyrebase.initialize_app(firebaseConfig)
    auth = firebase.auth()
    print("✔ Firebase Auth initialized.")
except Exception as e:
    print("❌ ERROR initializing Firebase Auth:", e)
    auth = None


# ============================================
# 3. FIRESTORE REST API BASE URL
# ============================================
PROJECT_ID = firebaseConfig["projectId"]
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"


# ============================================
# 4. HELPERS TO CONVERT PYTHON DICT → FIRESTORE REST FORMAT
# ============================================
def to_firestore_fields(data):
    """Convert Python dict to Firestore REST API fields format."""
    fields = {}

    for key, value in data.items():

        # String
        if isinstance(value, str):
            fields[key] = {"stringValue": value}

        # Integer
        elif isinstance(value, int):
            fields[key] = {"integerValue": str(value)}

        # Float
        elif isinstance(value, float):
            fields[key] = {"doubleValue": value}

        # Boolean
        elif isinstance(value, bool):
            fields[key] = {"booleanValue": value}

        # Dict (Map)
        elif isinstance(value, dict):
            fields[key] = {"mapValue": {"fields": to_firestore_fields(value)}}

        # List (Array)
        elif isinstance(value, list):
            fields[key] = {
                "arrayValue": {
                    "values": [
                        {"stringValue": str(v)} if isinstance(v, str)
                        else {"mapValue": {"fields": to_firestore_fields(v)}}
                        for v in value
                    ]
                }
            }

        else:
            fields[key] = {"stringValue": str(value)}

    return fields


# ============================================
# 5. FIRESTORE REST API FUNCTIONS (CORRECT AUTH)
# ============================================

def firestore_set(collection, document, data, id_token):
    url = f"{BASE_URL}/{collection}/{document}"
    headers = {"Authorization": f"Bearer {id_token}"}

    body = {"fields": to_firestore_fields(data)}
    res = requests.patch(url, headers=headers, json=body)
    return res.json()


def firestore_get(collection, document, id_token):
    url = f"{BASE_URL}/{collection}/{document}"
    headers = {"Authorization": f"Bearer {id_token}"}

    res = requests.get(url, headers=headers)
    return res.json()


def firestore_update(collection, document, data, id_token):
    url = f"{BASE_URL}/{collection}/{document}?updateMask.fieldPaths=*"
    headers = {"Authorization": f"Bearer {id_token}"}

    body = {"fields": to_firestore_fields(data)}
    res = requests.patch(url, headers=headers, json=body)
    return res.json()

def firestore_update_raw(collection, document, body, id_token):
    url = f"{BASE_URL}/{collection}/{document}?access_token={id_token}&updateMask.fieldPaths=steps"
    res = requests.patch(url, json=body)
    return res.json()


def firestore_list(collection, id_token):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/{collection}"
    headers = {"Authorization": f"Bearer {id_token}"}
    return requests.get(url, headers=headers).json()


import requests

PROJECT_ID = "fab-tracker-93819"
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

def firestore_get_collection(collection, id_token):
    url = f"{BASE_URL}/{collection}"
    headers = {"Authorization": f"Bearer {id_token}"}
    response = requests.get(url, headers=headers)
    return response.json()
