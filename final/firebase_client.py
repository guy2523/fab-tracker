

# firebase_client.py
import requests
import json
import streamlit as st

# ============================================
# 1. FIREBASE WEB CONFIG
# ============================================
firebaseConfig = {
    "apiKey": "AIzaSyC4ekPpnhhwNQU_w78-6NaeITIGe67gS8I",
    "authDomain": "fab-tracker-93819.firebaseapp.com",
    "projectId": "fab-tracker-93819",
    "storageBucket": "fab-tracker-93819.appspot.com",
    "messagingSenderId": "516510758182",
    "appId": "1:516510758182:web:a632746532b9d49f5a3de7",
    "databaseURL": "https://fab-tracker-93819.firebaseio.com"
}

# ============================================
# 2. AUTHENTICATION (REST API replaces Pyrebase)
# ============================================
API_KEY = firebaseConfig["apiKey"]

def firebase_sign_in(email, password):
    """Authenticate using Firebase REST API."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    payload = {
        "email": email,
        "password": password,
        "returnSecureToken": True
    }

    res = requests.post(url, json=payload)
    res.raise_for_status()
    return res.json()


def firebase_sign_in_with_google(google_id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key={API_KEY}"

    payload = {
        "postBody": f"id_token={google_id_token}&providerId=google.com",
        "requestUri": "http://localhost",
        "returnSecureToken": True,
    }

    res = requests.post(url, json=payload)
    res.raise_for_status()
    return res.json()




# ============================================
# 3. FIRESTORE REST API BASE URL
# ============================================
PROJECT_ID = firebaseConfig["projectId"]
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents"

# ============================================
# 4. HELPERS TO CONVERT PYTHON → FIRESTORE
# ============================================
def to_firestore_value(value):
    """Recursively encode Python values into Firestore REST format"""
    
    # None → null
    if value is None:
        return {"nullValue": None}

    # String
    if isinstance(value, str):
        return {"stringValue": value}

    # Integer
    if isinstance(value, int):
        return {"integerValue": str(value)}

    # Float
    if isinstance(value, float):
        return {"doubleValue": value}

    # Boolean
    if isinstance(value, bool):
        return {"booleanValue": value}

    # List
    if isinstance(value, list):
        return {
            "arrayValue": {
                "values": [to_firestore_value(v) for v in value]
            }
        }

    # Dict
    if isinstance(value, dict):
        return {
            "mapValue": {
                "fields": {k: to_firestore_value(v) for k, v in value.items()}
            }
        }

    # Fallback
    return {"stringValue": str(value)}


def to_firestore_fields(data: dict):
    """Top-level wrapper used in Firestore PATCH and SET"""
    return {k: to_firestore_value(v) for k, v in data.items()}




# ============================================
# 5. FIRESTORE REST API FUNCTIONS (CORRECT AUTH)
# ============================================


def firestore_list(collection, id_token):
    url = f"{BASE_URL}/{collection}"
    headers = {"Authorization": f"Bearer {id_token}"}
    return requests.get(url, headers=headers).json()


def firestore_set(collection, document, data, id_token):
    url = f"{BASE_URL}/{collection}/{document}"
    headers = {"Authorization": f"Bearer {id_token}"}

    # body = {"fields": to_firestore_fields(data)}
    # body = {"fields": {k: to_firestore_value(v) for k, v in data.items()}}
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


# def firestore_update_field(collection, document, field_path, value, id_token):
#     """
#     field_path example:
#       "metadata.fab.fabout"
#       "metadata.design.completed"
#     """
#     print("🔥 FIRESTORE UPDATE FIELD CALLED args=", locals())


#     url = (
#         f"{BASE_URL}/{collection}/{document}"
#         f"?updateMask.fieldPaths={field_path}"
#     )

#     headers = {
#         "Authorization": f"Bearer {id_token}",
#         "Content-Type": "application/json",
#     }

#     # Build nested Firestore field structure
#     def build_fields(path, val):
#         keys = path.split(".")
#         d = to_firestore_value(val)
#         for k in reversed(keys):
#             d = {"mapValue": {"fields": {k: d}}}
#         return d

#     # body = {"fields": build_fields(field_path, value)}
#     leaf_key = field_path.split(".")[-1]
#     body = {
#         "fields": {
#             leaf_key: to_firestore_value(value)
#         }
#     }

#     res = requests.patch(url, headers=headers, json=body)
#     return res.json()

def firestore_update_field(collection, document, field_path, value, id_token):
    """
    Supports deep nested updates like:
      metadata.measure.fridges.fridge_xxx.notion
      metadata.package.chips.chip_yyy.pcb_ready
      metadata.fab.fabout
    """

    # print("🔥 FIRESTORE UPDATE FIELD CALLED args=", locals())
    print(
        "🔥 FIRESTORE UPDATE FIELD CALLED",
        {
            "collection": collection,
            "document": document,
            "field_path": field_path,
            "value_type": type(value).__name__,
            "value_keys": list(value.keys()) if isinstance(value, dict) else None,
        }
    )


    url = (
        f"{BASE_URL}/{collection}/{document}"
        f"?updateMask.fieldPaths={field_path}"
    )

    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json",
    }

    # Build ONLY the subtree required by updateMask
    keys = field_path.split(".")

    node = to_firestore_value(value)  # leaf value

    for k in reversed(keys):
        node = {
            "mapValue": {
                "fields": {
                    k: node
                }
            }
        }

    body = {
        "fields": node["mapValue"]["fields"]
    }

    res = requests.patch(url, headers=headers, json=body)
    return res.json()



def firestore_list(collection, id_token):
    url = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)/documents/{collection}"
    headers = {"Authorization": f"Bearer {id_token}"}
    return requests.get(url, headers=headers).json()

def firestore_delete(collection, document, id_token):
    url = f"{BASE_URL}/{collection}/{document}"
    headers = {"Authorization": f"Bearer {id_token}"}
    res = requests.delete(url, headers=headers)
    return res.status_code, res.text



def firestore_to_python(v):
    if not isinstance(v, dict):
        return v

    # primitive values
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return bool(v["booleanValue"])
    if "timestampValue" in v:          # ← THIS LINE FIXES IT
        return v["timestampValue"]

    # ARRAY — PRESERVE ORDER
    if "arrayValue" in v:
        arr = v["arrayValue"].get("values", [])
        out = []

        for item in arr:
            if "mapValue" in item:
                fields = item["mapValue"].get("fields", {})

                # metadata-style array element
                if "key" in fields and "value" in fields:
                    out.append({
                        "key": firestore_to_python(fields["key"]),
                        "value": firestore_to_python(fields["value"]),
                    })
                else:
                    # generic map inside array (substeps, chips, presets)
                    out.append({
                        kk: firestore_to_python(vv)
                        for kk, vv in fields.items()
                    })
            else:
                out.append(firestore_to_python(item))

        return out

    # MAP
    if "mapValue" in v:
        fields = v["mapValue"].get("fields", {})

        # metadata-style map (key/value pair)
        if "key" in fields and "value" in fields:
            return {
                "key": firestore_to_python(fields["key"]),
                "value": firestore_to_python(fields["value"]),
            }

        # generic Firestore map
        return {
            kk: firestore_to_python(vv)
            for kk, vv in fields.items()
        }

    return v


def firebase_refresh_id_token(refresh_token: str):
    # ✅ Use the same Firebase Web API key as sign-in
    api_key = API_KEY

    url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    r = requests.post(url, data=payload, timeout=10)
    r.raise_for_status()

    data = r.json()

    return {
        "id_token": data["id_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": int(data["expires_in"]),
    }
