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

from config import load_config, safe_join, safe_filename

def ingest_archive_to_library(
    archive_path_str: str,
    author: str,
    month: str,
    password: str = "f95zone"
) -> Dict[str, Any]:
    """
    Extracts an archive safely into H:\akinaclub\<author>\<month>,
    then removes the original archive only if extraction fully succeeds.
    """
    try:
        archive_path = Path(archive_path_str).resolve()
    except Exception as e:
        return {"status": "error", "message": f"路径无效: {str(e)}"}

    if not archive_path.exists() or not archive_path.is_file():
        return {"status": "error", "message": "压缩包文件不存在"}

    if archive_path.suffix.lower() not in ARCHIVE_EXTS:
        return {"status": "error", "message": f"不支持的文件类型: {archive_path.suffix}"}

    cfg = load_config()
    lib_root = Path(cfg.get("library_root", r"H:\akinaclub"))
    
    # Security check: ensure archive_path is inside allowed directories
    allowed_roots = [
        Path(os.path.expanduser(r"~\Downloads")).resolve(),
        (Path(__file__).parent / "downloads").resolve(),
        lib_root.resolve()
    ]
    is_allowed = False
    for root in allowed_roots:
        try:
            archive_path.relative_to(root)
            is_allowed = True
            break
        except ValueError:
            pass

    if not is_allowed:
        return {"status": "error", "message": "安全限制：待归档文件必须位于下载目录或素材库目录内"}

    try:
        clean_author = safe_filename(author)
        clean_month = safe_filename(month)
        target_dir = safe_join(lib_root, clean_author, clean_month)
    except Exception as e:
        return {"status": "error", "message": f"路径校验不合法: {str(e)}"}

    passwords = [password, "f95zone", author]
    ok, msg = extract_archive(archive_path, target_dir, passwords=passwords)
    if not ok:
        return {"status": "error", "message": f"解压失败: {msg}"}

    # Delete source archive only after verified successful extraction
    if cfg.get("delete_archive_after_extract", True):
        try:
            archive_path.unlink(missing_ok=True)
        except Exception as e:
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
