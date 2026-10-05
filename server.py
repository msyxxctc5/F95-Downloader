import os
import sys
import json
import logging
import threading
import urllib.parse
from pathlib import Path
from typing import Dict, List, Any, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uvicorn

from config import (
    load_config, save_config, get_request_cookies,
    get_library_root, get_download_dir, get_user_agent,
    safe_join, safe_filename, atomic_write_json
)
from scanner import scan_all_authors, scan_author_directory, invalidate_author_cache
from diff_engine import compare_local_vs_f95, unmask_f95_link, unmask_f95_link_detailed
from downloader import DownloadJob, resolve_direct_download_url
from idm_helper import download_with_idm, find_idm_path
from ingest import scan_downloads_folder, ingest_archive_to_library
from f95_search import search_f95_threads

logger = logging.getLogger("akinasync.server")

app = FastAPI(title="AkinaSync - F95zone Collection Updater")

@app.middleware("http")
async def validate_host_and_origin(request: Request, call_next):
    host_header = request.headers.get("host", "")
    hostname = host_header.split(":")[0].lower() if host_header else ""
    allowed = {"127.0.0.1", "localhost", "testserver"}
    if hostname and hostname not in allowed:
        return Response(status_code=403, content="Forbidden: Invalid Host header")
        
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed_origin = urllib.parse.urlparse(origin)
            if parsed_origin.hostname and parsed_origin.hostname.lower() not in allowed:
                return Response(status_code=403, content="Forbidden: Cross-Origin Request Blocked")
        except Exception:
            return Response(status_code=403, content="Forbidden: Invalid Origin header")
            
    return await call_next(request)

def is_valid_f95_thread_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return (
            parsed.scheme == "https"
            and parsed.netloc.lower() in ("f95zone.to", "www.f95zone.to")
            and parsed.path.startswith("/threads/")
        )
    except Exception:
        return False

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
ARTISTS_FILE = DATA_DIR / "artists.json"

# In-memory tracking of active download jobs
active_jobs: Dict[str, DownloadJob] = {}

_artists_lock = threading.Lock()

def get_saved_artists() -> Dict[str, Any]:
    with _artists_lock:
        if not ARTISTS_FILE.exists():
            init_data = {}
            from config import atomic_write_json
            atomic_write_json(ARTISTS_FILE, init_data)
            return init_data
        try:
            with open(ARTISTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def save_artists(data: Dict[str, Any]):
    from config import atomic_write_json
    with _artists_lock:
        atomic_write_json(ARTISTS_FILE, data)

class BindArtistRequest(BaseModel):
    author: str
    thread_url: str

class UnbindArtistRequest(BaseModel):
    author: str

class StartDownloadRequest(BaseModel):
    author: str
    month: str
    masked_url: str
    password: Optional[str] = "f95zone"

class ConfigUpdateRequest(BaseModel):
    xf_user: Optional[str] = None
    cf_clearance: Optional[str] = None
    library_root: Optional[str] = None
    download_dir: Optional[str] = None
    user_agent: Optional[str] = None
    delete_archive_after_extract: Optional[bool] = None

def mask_cookie_val(val: Optional[str]) -> str:
    if not val:
        return ""
    if len(val) <= 10:
        return "******"
    return val[:4] + "******" + val[-4:]

# --- API Endpoints ---
@app.get("/api/config")
def get_config():
    cfg = load_config()
    safe = cfg.copy()
    raw_xf = safe.pop("xf_user", None)
    if raw_xf:
        safe["xf_user_masked"] = mask_cookie_val(raw_xf)
        safe["has_xf_user"] = True
    else:
        safe["has_xf_user"] = False
    safe["library_root"] = str(get_library_root())
    safe["download_dir"] = str(get_download_dir())
    safe["user_agent"] = get_user_agent()
    return safe

@app.post("/api/config")
def update_config(req: ConfigUpdateRequest):
    cfg = load_config()
    if req.xf_user is not None and req.xf_user.strip():
        cfg["xf_user"] = req.xf_user.strip()
    if req.cf_clearance is not None:
        cfg["cf_clearance"] = req.cf_clearance.strip()
    if req.library_root is not None and req.library_root.strip():
        cfg["library_root"] = req.library_root.strip()
    if req.download_dir is not None and req.download_dir.strip():
        cfg["download_dir"] = req.download_dir.strip()
    if req.user_agent is not None and req.user_agent.strip():
        cfg["user_agent"] = req.user_agent.strip()
    if req.delete_archive_after_extract is not None:
        cfg["delete_archive_after_extract"] = req.delete_archive_after_extract
    save_config(cfg)
    return {"status": "ok", "config": get_config()}

@app.get("/api/library/status")
def get_library_status():
    from fastcache import STATE
    lib_root = get_library_root()
    return {
        "online": lib_root.exists(),
        "library_root": str(lib_root),
        **STATE
    }

@app.get("/api/authors")
def list_local_authors(force: bool = False):
    lib_root = str(get_library_root())
    saved = get_saved_artists()
    
    if force:
        authors = scan_all_authors(lib_root, force=True)
    else:
        from fastcache import list_cached, start_background_revalidate
        authors, online = list_cached(lib_root)
        if online:
            start_background_revalidate(lib_root)

    # Merge with saved thread info
    for a in authors:
        info = saved.get(a["name"])
        if info:
            a["thread_url"] = info.get("thread_url")
            a["missing_count"] = info.get("missing_count", 0)
        else:
            a["thread_url"] = None
            a["missing_count"] = 0
    return authors

@app.get("/api/f95/search")
def search_author_threads(q: str):
    return search_f95_threads(q, limit=6)

@app.post("/api/authors/bind")
def bind_author_thread(req: BindArtistRequest):
    if not is_valid_f95_thread_url(req.thread_url):
        raise HTTPException(status_code=400, detail="非法专楼链接：仅支持 https://f95zone.to/threads/ 论坛原帖链接")
    saved = get_saved_artists()
    saved.setdefault(req.author, {})
    saved[req.author]["name"] = req.author
    saved[req.author]["thread_url"] = req.thread_url
    save_artists(saved)
    return {"status": "ok", "artist": saved[req.author]}

@app.post("/api/authors/unbind")
def unbind_author_thread(req: UnbindArtistRequest):
    saved = get_saved_artists()
    if req.author in saved:
        saved[req.author]["thread_url"] = None
        saved[req.author]["missing_count"] = 0
        save_artists(saved)
    return {"status": "ok", "author": req.author}

def launch_explorer_interactive(target_path: str, is_file: bool = False) -> bool:
    import subprocess
    norm = os.path.normpath(target_path)

    # Cross-platform support for non-Windows operating systems
    if os.name != 'nt':
        try:
            target_to_open = os.path.dirname(norm) if is_file else norm
            if sys.platform == 'darwin':
                subprocess.Popen(['open', target_to_open])
            else:
                subprocess.Popen(['xdg-open', target_to_open])
            return True
        except Exception as e:
            logger.warning("Failed to open file manager on %s: %s", sys.platform, e)
            return False

    # Windows implementation
    if is_file:
        tr_cmd = f'explorer.exe /select,"{norm}"'
    else:
        tr_cmd = f'explorer.exe "{norm}"'
        
    tn = "F95_OpenFolder"
    try:
        # Use Windows Task Scheduler with /it (Interactive) to break through virtual desktop isolation
        subprocess.run([
            'schtasks', '/create',
            '/tn', tn,
            '/tr', tr_cmd,
            '/sc', 'once',
            '/st', '00:00',
            '/it',
            '/f'
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['schtasks', '/run', '/tn', tn], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as sch_err:
        logger.debug("schtasks launch failed, falling back to direct explorer.exe: %s", sch_err)
        si = subprocess.STARTUPINFO()
        si.lpDesktop = r"WinSta0\default"
        try:
            if is_file:
                subprocess.Popen(['explorer.exe', f'/select,{norm}'], startupinfo=si)
            else:
                subprocess.Popen(['explorer.exe', norm], startupinfo=si)
            return True
        except Exception as exp_err:
            logger.debug("direct explorer.exe launch failed, trying os.startfile: %s", exp_err)
            if hasattr(os, "startfile"):
                try:
                    os.startfile(norm)
                    return True
                except Exception as sf_err:
                    logger.warning("os.startfile failed: %s", sf_err)
                    return False
            return False

class OpenFolderRequest(BaseModel):
    author: str
    subpath: Optional[str] = None

@app.post("/api/authors/open_folder")
def open_author_folder(req: OpenFolderRequest):
    lib_root = get_library_root()
    
    try:
        clean_author = safe_filename(req.author)
        target = safe_join(lib_root, clean_author)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"非法路径: {str(e)}")

    if not target.exists() and lib_root.exists():
        for child in lib_root.iterdir():
            if child.is_dir() and child.name.lower() == req.author.lower():
                target = child
                break

    if req.subpath:
        try:
            sub = safe_join(target, *req.subpath.replace("\\", "/").split("/"))
            if sub.exists():
                target = sub
        except Exception as sub_err:
            logger.debug("Subpath join error: %s", sub_err)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"目录或文件 '{target}' 未找到")
        
    norm_path = os.path.normpath(str(target))
    success = launch_explorer_interactive(norm_path, is_file=target.is_file())
    if success:
        return {"status": "ok", "opened": norm_path}
    else:
        raise HTTPException(status_code=500, detail="无法启动系统文件管理器")

@app.get("/api/diff")
def get_author_diff(author: str, thread_url: Optional[str] = None, force: bool = False):
    saved = get_saved_artists()
    url = thread_url or (saved.get(author, {}).get("thread_url"))
    if not url:
        raise HTTPException(status_code=400, detail="未提供专楼链接，请先绑定专楼或输入链接")
    if not is_valid_f95_thread_url(url):
        raise HTTPException(status_code=400, detail="非法专楼链接：仅支持 https://f95zone.to/threads/ 论坛原帖链接")
    
    try:
        res = compare_local_vs_f95(author, url, force=force)
        if "error" in res:
            logger.warning("Diff failed for %s: %s", author, res["error"])
            raise HTTPException(status_code=502, detail=res["error"])
        # Update missing count in saved
        if author in saved:
            saved[author]["missing_count"] = res.get("missing_count", 0)
            save_artists(saved)
        return res
    except HTTPException:
        raise
    except RuntimeError as re:
        logger.warning("Runtime error diffing author %s: %s", author, re)
        raise HTTPException(status_code=502, detail=str(re))
    except Exception as e:
        logger.error("Unexpected error diffing author %s: %s", author, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/download/start")
def start_download(req: StartDownloadRequest, background_tasks: BackgroundTasks):
    job_id = f"{req.author}_{req.month}"
    if job_id in active_jobs:
        curr = active_jobs[job_id].status
        if curr not in ("FAILED", "CANCELLED", "COMPLETED", "DONE"):
            return {"status": "already_running", "job_id": job_id}

    job = DownloadJob(
        author=req.author,
        month=req.month,
        masked_url=req.masked_url,
        password=req.password or "f95zone"
    )
    active_jobs[job_id] = job

    def run_worker():
        job.run()

    threading.Thread(target=run_worker, daemon=True).start()
    return {"status": "started", "job_id": job_id}

class IngestRequest(BaseModel):
    archive_path: str
    author: str
    month: str
    password: Optional[str] = "f95zone"

@app.get("/api/downloads/scan")
def scan_downloads_endpoint():
    return scan_downloads_folder()

@app.post("/api/downloads/ingest")
def ingest_endpoint(req: IngestRequest):
    p = Path(req.archive_path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=400, detail="指定的压缩包文件不存在")
    if p.suffix.lower() not in ('.zip', '.rar', '.7z', '.tar', '.gz'):
        raise HTTPException(status_code=400, detail="不支持的文件格式")
    res = ingest_archive_to_library(req.archive_path, req.author, req.month, req.password or "f95zone")
    if res.get("status") == "ok":
        invalidate_author_cache(req.author)
    return res

class IDMRequest(BaseModel):
    author: str
    month: str
    masked_url: str

@app.get("/api/idm/status")
def check_idm_status():
    p = find_idm_path()
    return {"installed": bool(p), "path": p}

@app.post("/api/idm/download")
def idm_download_endpoint(req: IDMRequest):
    cookies = get_request_cookies()
    real_url, unmask_err = unmask_f95_link_detailed(req.masked_url, cookies)
    if not real_url:
        detail = unmask_err or "无法解析直链"
        logger.warning("IDM download unmask failed: %s", detail)
        raise HTTPException(status_code=400, detail=detail)
    direct_url, fname = resolve_direct_download_url(real_url)
    target_url = direct_url if direct_url else real_url
    ok = download_with_idm(target_url, filename=fname)
    if not ok:
        raise HTTPException(status_code=500, detail="调用 IDM 失败，请检查 IDM 是否已安装并在运行")
    return {"status": "ok", "url": target_url, "filename": fname}

@app.get("/api/download/direct_url")
def get_direct_url(masked_url: str):
    cookies = get_request_cookies()
    real_url, unmask_err = unmask_f95_link_detailed(masked_url, cookies)
    if not real_url:
        return {"target_url": masked_url, "is_stream": False, "real_url": masked_url, "error": unmask_err}

    direct_url, fname = resolve_direct_download_url(real_url)
    if direct_url:
        return {"target_url": direct_url, "is_stream": True, "real_url": real_url, "filename": fname}
    else:
        return {"target_url": real_url, "is_stream": False, "real_url": real_url}

@app.get("/api/unmask")
def unmask_endpoint(url: str):
    cookies = get_request_cookies()
    real_url, unmask_err = unmask_f95_link_detailed(url, cookies)
    if not real_url:
        detail = unmask_err or "解析反代直链失败"
        logger.warning("Unmask endpoint failed for %s: %s", url, detail)
        raise HTTPException(status_code=400, detail=detail)
    return {"status": "ok", "real_url": real_url}

@app.post("/api/jobs/clear")
def clear_jobs():
    global active_jobs
    active_jobs = {k: v for k, v in active_jobs.items() if v.status in ("DOWNLOADING", "EXTRACTING")}
    return {"status": "ok"}

@app.get("/api/jobs")
def get_jobs_status():
    result = {}
    for jid, job in active_jobs.items():
        result[jid] = {
            "author": job.author,
            "month": job.month,
            "status": job.status,
            "progress": job.progress,
            "downloaded_size": job.downloaded_size,
            "total_size": job.total_size,
            "speed": job.speed_str,
            "error": job.error_msg,
            "final_path": job.final_path
        }
    return result

# Serve Frontend
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def serve_index():
    index_html = STATIC_DIR / "index.html"
    if index_html.exists():
        return FileResponse(index_html)
    return HTMLResponse("<h1>AkinaSync UI is building...</h1>")

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8899, reload=False)
