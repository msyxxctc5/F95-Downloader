import os
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from scanner import normalize_month
from extractor import extract_archive
from config import load_config

ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.tar', '.gz'}

def scan_downloads_folder(downloads_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scans the user's Downloads folder for pending archive files.
    """
    if not downloads_dir:
        downloads_dir = os.path.expanduser(r"~\Downloads")
        
    p = Path(downloads_dir)
    if not p.exists():
        return []

    results = []
    for item in p.iterdir():
        if item.is_file() and item.suffix.lower() in ARCHIVE_EXTS:
            month = normalize_month(item.name)
            results.append({
                "filename": item.name,
                "path": str(item),
                "size_mb": round(item.stat().st_size / (1024 * 1024), 2),
                "detected_month": month or None
            })
            
    return sorted(results, key=lambda x: x["filename"].lower())

def ingest_archive_to_library(
    archive_path_str: str,
    author: str,
    month: str,
    password: str = "f95zone"
) -> Dict[str, Any]:
    """
    Extracts an archive from Downloads directly into H:\akinaclub\<author>\<month>,
    then removes the original archive.
    """
    archive_path = Path(archive_path_str)
    if not archive_path.exists():
        return {"status": "error", "message": "文件不存在"}

    cfg = load_config()
    lib_root = Path(cfg.get("library_root", r"H:\akinaclub"))
    target_dir = lib_root / author / month
    target_dir.mkdir(parents=True, exist_ok=True)

    passwords = [password, "f95zone", author]
    ok, msg = extract_archive(archive_path, target_dir, passwords=passwords)
    if not ok:
        return {"status": "error", "message": f"解压失败: {msg}"}

    # Delete source archive if configured
    if cfg.get("delete_archive_after_extract", True):
        try:
            archive_path.unlink()
        except Exception:
            pass

    return {
        "status": "ok",
        "target_dir": str(target_dir),
        "message": f"成功归档至 {target_dir}"
    }

if __name__ == "__main__":
    items = scan_downloads_folder()
    print("Found archives in Downloads:", len(items))
    for it in items[:5]:
        print(it)
