
import json
import streamlit as st
import base64
import requests


def upload_file_via_cleanroom_api(*, uploaded_file, filename: str, folder_id: str):
    url = st.secrets["app"]["cleanroom_logger_webapp_url"]

    file_bytes = uploaded_file.getvalue()
    payload = {
        "drive_upload": True,
        "folder_id": folder_id,
        "filename": filename,
        "mime_type": uploaded_file.type or "application/octet-stream",
        "file_base64": base64.b64encode(file_bytes).decode(),
    }

    r = requests.post(
        url,
        json=payload,
        timeout=60,
    )

    # Debug (you already saw this working)
    st.write("STATUS:", r.status_code)
    st.write("TEXT:", r.text)

    if r.status_code != 200:
        raise RuntimeError(f"Upload failed: {r.text}")

    # ✅ THIS IS THE FIX
    try:
        return r.json()
    except Exception:
        raise RuntimeError(f"Invalid JSON response: {r.text}")

def delete_file_via_cleanroom_api(*, file_id: str):
    url = st.secrets["app"]["cleanroom_logger_webapp_url"]
    payload = {"drive_delete": True, "file_id": file_id}

    r = requests.post(url, json=payload, timeout=60)

    if r.status_code != 200:
        return {"success": False, "error": f"HTTP {r.status_code}: {r.text[:2000]}"}

    try:
        return r.json()
    except Exception:
        return {"success": False, "error": f"Non-JSON response: {r.text[:2000]}"}
