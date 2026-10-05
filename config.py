import json
import os
import re
import uuid
import shutil
import threading
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("akinasync.config")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s", "%Y-%m-%d %H:%M:%S")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

CONFIG_FILE = Path(__file__).parent / "config.json"
_file_lock = threading.Lock()

DEFAULT_CONFIG: Dict[str, Any] = {
    "library_root": str(Path.home() / "Downloads" / "library"),
    "xf_user": "",
    "cf_clearance": "",
    "full_cookie": "",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "preferred_mirrors": ["pixeldrain", "gofile", "workupload", "mega"],
    "download_dir": "downloads",
    "auto_extract": True,
    "delete_archive_after_extract": True,
    "known_passwords": ["f95zone", "f95"],
    "seven_zip_path": ""
}

def get_library_root() -> Path:
    """Returns the resolved library root directory from config, falling back to user's home Downloads."""
    cfg = load_config()
    raw = cfg.get("library_root")
    if raw and str(raw).strip():
        return Path(raw).expanduser()
    return Path.home() / "Downloads" / "library"

def get_download_dir() -> Path:
    """Returns the resolved download directory from config, supporting relative paths."""
    cfg = load_config()
    raw = cfg.get("download_dir")
    if raw and str(raw).strip():
        p = Path(raw).expanduser()
        if not p.is_absolute():
            return (Path(__file__).parent / p).resolve()
        return p
    return (Path(__file__).parent / "downloads").resolve()

def get_user_agent() -> str:
    """Returns the configured User-Agent string."""
    cfg = load_config()
    ua = cfg.get("user_agent")
    if ua and str(ua).strip():
        return str(ua).strip()
    return str(DEFAULT_CONFIG["user_agent"])

def get_7z_custom_path() -> Optional[str]:
    """Returns the optional user-configured 7-Zip binary path."""
    cfg = load_config()
    p = cfg.get("seven_zip_path")
    if p and str(p).strip():
        return str(p).strip()
    return None

def safe_join(root: Path, *parts: str) -> Path:
    """
    Safely joins path parts to root, preventing directory traversal out of root.
    Avoids using resolve() on root so mapped drives (e.g. H:) aren't converted to UNC.
    """
    root_abs = Path(os.path.abspath(root))
    clean_parts = []
    for p in parts:
        clean_parts.extend(Path(str(p).replace("\\", "/")).parts)
    filtered = [p for p in clean_parts if p not in ("/", "\\", "..", ".")]
    target = Path(os.path.abspath(root_abs.joinpath(*filtered)))
    if target != root_abs and root_abs not in target.parents:
        raise ValueError(f"Path escape detected: {target} is outside {root_abs}")
    return target

def safe_filename(name: str) -> str:
    """Sanitizes filename from untrusted source."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')
    return s or "_"

def atomic_write_json(file_path: Path, data: Any):
    """Writes data to a temporary file first, then atomically renames to target file."""
    with _file_lock:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = file_path.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, file_path)

def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            cfg = DEFAULT_CONFIG.copy()
            cfg.update(data)
            return cfg
    except Exception as e:
        logger.error("Failed to parse config.json, recovering from backup: %s", e)
        bak = CONFIG_FILE.with_suffix(".json.bak")
        try:
            shutil.copy(CONFIG_FILE, bak)
        except Exception as bak_err:
            logger.warning("Could not backup corrupted config file: %s", bak_err)
        return DEFAULT_CONFIG.copy()

def save_config(cfg: Dict[str, Any]):
    atomic_write_json(CONFIG_FILE, cfg)

def get_request_cookies() -> Dict[str, str]:
    cfg = load_config()
    cookies = {}
    if cfg.get("xf_user"):
        cookies["xf_user"] = cfg["xf_user"]
    if cfg.get("cf_clearance"):
        cookies["cf_clearance"] = cfg["cf_clearance"]
    if cfg.get("full_cookie"):
        for part in cfg["full_cookie"].split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                cookies[k] = v
    return cookies

if __name__ == "__main__":
    cfg = load_config()
    sanitized = {k: ("******" if "user" in k or "cookie" in k or "clearance" in k else v) for k, v in cfg.items()}
    print("Config loaded (sanitized):", sanitized)
