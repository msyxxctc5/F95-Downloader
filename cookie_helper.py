import os
import json
import base64
import sqlite3
import shutil
import tempfile
import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from typing import Dict, Optional

def get_encryption_key(local_state_path: str) -> Optional[bytes]:
    if not os.path.exists(local_state_path):
        return None
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            local_state = json.load(f)
        encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
        # Remove 'DPAPI' prefix (first 5 bytes)
        encrypted_key = encrypted_key[5:]
        key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
        return key
    except Exception as e:
        return None

def decrypt_cookie_value(encrypted_val: bytes, key: bytes) -> str:
    try:
        # Check prefix: v10 or v11
        if encrypted_val[:3] in (b'v10', b'v11'):
            nonce = encrypted_val[3:15]
            ciphertext = encrypted_val[15:]
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode('utf-8', errors='ignore')
        else:
            # DPAPI fallback for older formats
            decrypted = win32crypt.CryptUnprotectData(encrypted_val, None, None, None, 0)[1]
            return decrypted.decode('utf-8', errors='ignore')
    except Exception:
        return ""

def load_f95_cookies_from_browser(browser_name: str = "edge") -> Dict[str, str]:
    """
    Attempt to load f95zone.to cookies from Chrome or Edge.
    """
    app_data = os.environ.get("LOCALAPPDATA", "")
    if browser_name.lower() == "chrome":
        user_data = os.path.join(app_data, r"Google\Chrome\User Data")
    else:
        user_data = os.path.join(app_data, r"Microsoft\Edge\User Data")

    local_state = os.path.join(user_data, "Local State")
    key = get_encryption_key(local_state)
    if not key:
        return {}

    # Look for Cookie db in all directories in user_data
    cookies = {}
    for entry in os.listdir(user_data):
        prof_dir = os.path.join(user_data, entry)
        if not os.path.isdir(prof_dir):
            continue
        cookie_db_path = os.path.join(prof_dir, "Network", "Cookies")
        if not os.path.exists(cookie_db_path):
            cookie_db_path = os.path.join(prof_dir, "Cookies")
            if not os.path.exists(cookie_db_path):
                continue

        # Copy to temp file to avoid SQLite lock if browser is running
        temp_dir = tempfile.gettempdir()
        temp_db = os.path.join(temp_dir, f"temp_cookies_{browser_name}_{entry}.sqlite")
        try:
            shutil.copyfile(cookie_db_path, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%f95zone%'"
            )
            rows = cursor.fetchall()
            for name, encrypted_value in rows:
                val = decrypt_cookie_value(encrypted_value, key)
                if val:
                    cookies[name] = val
            conn.close()
            try:
                os.remove(temp_db)
            except Exception:
                pass
            if 'xf_user' in cookies:
                break
        except Exception as e:
            continue

    return cookies

def get_f95_cookies() -> Dict[str, str]:
    # Try Edge first, then Chrome
    cookies = load_f95_cookies_from_browser("edge")
    if not cookies or 'xf_user' not in cookies:
        chrome_cookies = load_f95_cookies_from_browser("chrome")
        if chrome_cookies:
            cookies = chrome_cookies
    return cookies

if __name__ == "__main__":
    c = get_f95_cookies()
    print("Found cookies count:", len(c))
    print("Cookie keys:", list(c.keys()))
    if 'xf_user' in c:
        print("Logged in as user token found! Success!")
    else:
        print("xf_user cookie not found (might not be logged into f95zone in Edge/Chrome, or stored elsewhere).")
