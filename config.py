import json
import os
from pathlib import Path
from typing import Dict, Any

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "library_root": r"H:\akinaclub",
    "xf_user": "",
    "cf_clearance": "",
    "full_cookie": "",
    "preferred_mirrors": ["pixeldrain", "gofile", "workupload", "mega"],
    "download_dir": r"c:\Users\Despa\Desktop\Dev\downloads",
    "auto_extract": True,
    "delete_archive_after_extract": True,
    "known_passwords": ["f95zone", "f95"]
}

def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge defaults
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def get_request_cookies() -> Dict[str, str]:
    cfg = load_config()
    cookies = {}
    if cfg.get("xf_user"):
        cookies["xf_user"] = cfg["xf_user"]
    if cfg.get("cf_clearance"):
        cookies["cf_clearance"] = cfg["cf_clearance"]
    if cfg.get("full_cookie"):
        # Parse "key=value; key2=value2"
        for part in cfg["full_cookie"].split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
    return cookies

if __name__ == "__main__":
    cfg = load_config()
    print("Config loaded:", cfg)
