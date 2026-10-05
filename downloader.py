import os
import re
import time
import logging
import threading
import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional, Tuple

from config import (
    load_config, get_request_cookies, get_download_dir,
    get_library_root, get_user_agent, safe_join, safe_filename
)
from diff_engine import unmask_f95_link_detailed
from extractor import extract_archive

logger = logging.getLogger("akinasync.downloader")

_unmask_lock = threading.Lock()
_last_unmask_time = 0.0

def rate_limited_unmask(masked_url: str, cookies: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Serializes unmask requests with a mandatory cooldown (1.2s) to prevent Cloudflare/F95zone bans.
    """
    global _last_unmask_time
    with _unmask_lock:
        now = time.time()
        elapsed = now - _last_unmask_time
        if elapsed < 1.2:
            time.sleep(1.2 - elapsed)
        try:
            real_url, err = unmask_f95_link_detailed(masked_url, cookies)
            _last_unmask_time = time.time()
            return real_url, err
        except Exception as e:
            _last_unmask_time = time.time()
            logger.error("Exception during rate-limited unmask of %s: %s", masked_url, e)
            return None, str(e)

def resolve_direct_download_url(real_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Given a cloud drive URL, resolve it to direct downloadable stream URL and filename.
    Returns: (download_url, filename)
    """
    # 1. Pixeldrain single file /u/
    px_match = re.search(r'pixeldrain\.com/u/([a-zA-Z0-9]+)', real_url)
    if px_match:
        file_id = px_match.group(1)
        fname = f"pixeldrain_{file_id}.zip"
        try:
            headers = {'User-Agent': get_user_agent()}
            info_res = requests.get(f"https://pixeldrain.com/api/file/{file_id}/info", headers=headers, timeout=10)
            if info_res.status_code == 200:
                data = info_res.json()
                fname = data.get("name", fname)
        except Exception as e:
            logger.debug("Pixeldrain file info check skipped: %s", e)
        return f"https://pixeldrain.com/api/file/{file_id}", fname

    # 2. Pixeldrain folder/list /l/
    px_list_match = re.search(r'pixeldrain\.com/l/([a-zA-Z0-9]+)', real_url)
    if px_list_match:
        list_id = px_list_match.group(1)
        fname = f"pixeldrain_list_{list_id}.zip"
        try:
            headers = {'User-Agent': get_user_agent()}
            info_res = requests.get(f"https://pixeldrain.com/api/list/{list_id}", headers=headers, timeout=10)
            if info_res.status_code == 200:
                data = info_res.json()
                title = data.get("title")
                if title:
                    fname = f"{title}.zip"
        except Exception as e:
            logger.debug("Pixeldrain list info check skipped: %s", e)
        return f"https://pixeldrain.com/api/list/{list_id}/zip", fname

    # Other cloud hosts (Mega, Workupload with captcha) cannot be directly fetched via simple stream GET
    return None, None

class DownloadJob:
    def __init__(self, author: str, month: str, masked_url: str, password: str = "f95zone"):
        self.author = author
        self.month = month
        self.masked_url = masked_url
        self.password = password
        self.status = "PENDING"
        self.progress = 0.0
        self.total_size = 0
        self.downloaded_size = 0
        self.speed_str = "0 KB/s"
        self.error_msg = ""
        self.final_path = ""
        self.real_url = ""

    def run(self, progress_callback: Optional[Callable[['DownloadJob'], None]] = None):
        cfg = load_config()
        cookies = get_request_cookies()
        dl_dir = get_download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        lib_root = get_library_root()

        try:
            # 1. Unmask link with rate limiting
            self.status = "UNMASKING"
            if progress_callback:
                progress_callback(self)

            real_url, unmask_err = rate_limited_unmask(self.masked_url, cookies)
            if not real_url:
                err_detail = unmask_err or "无法解析 F95zone 反代跳转链接"
                logger.warning("Unmask failed for job %s_%s: %s", self.author, self.month, err_detail)
                raise Exception(err_detail)
            self.real_url = real_url

            # 2. Check if host supports direct backend downloading
            direct_url, fname = resolve_direct_download_url(real_url)
            if not direct_url:
                raise Exception(f"该网盘不支持后台直接下载 (如 Mega/Workupload 需浏览器客户端)，请点击「在浏览器中打开网盘」进行下载: {real_url}")

            if not fname:
                fname = f"{safe_filename(self.author)}_{safe_filename(self.month)}.zip"
            else:
                fname = safe_filename(fname)

            local_file = safe_join(dl_dir, fname)
            part_file = local_file.with_name(f"{local_file.name}.part")

            # 3. Download stream to .part file with retry and integrity check
            self.status = "DOWNLOADING"
            if progress_callback:
                progress_callback(self)

            max_retries = 3
            last_download_error = None
            download_success = False

            for attempt in range(1, max_retries + 1):
                part_file.unlink(missing_ok=True)
                try:
                    headers = {
                        'User-Agent': get_user_agent()
                    }
                    with requests.get(direct_url, headers=headers, stream=True, timeout=35) as r:
                        r.raise_for_status()
                        
                        # Check Content-Type to prevent saving HTML error pages
                        content_type = r.headers.get('content-type', '').lower()
                        if 'text/html' in content_type:
                            raise Exception(f"网盘返回了 HTML 验证页面而非文件内容，请在浏览器中打开网盘下载: {real_url}")

                        total_length = r.headers.get('content-length')
                        expected_size = int(total_length) if total_length and total_length.isdigit() else 0
                        self.total_size = expected_size

                        downloaded = 0
                        start_time = time.time()
                        last_time = start_time
                        last_bytes = 0

                        with open(part_file, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=1024 * 512):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    self.downloaded_size = downloaded
                                    
                                    now = time.time()
                                    if now - last_time >= 0.5:
                                        speed = (downloaded - last_bytes) / (now - last_time)
                                        self.speed_str = f"{speed / (1024 * 1024):.2f} MB/s" if speed > 1024*1024 else f"{speed / 1024:.1f} KB/s"
                                        last_time = now
                                        last_bytes = downloaded
                                        if self.total_size > 0:
                                            self.progress = round((downloaded / self.total_size) * 100, 1)
                                        if progress_callback:
                                            progress_callback(self)

                    # Integrity verification of downloaded part file
                    actual_size = part_file.stat().st_size
                    if expected_size > 0 and actual_size != expected_size:
                        raise Exception(f"下载不完整: 实际获取 {actual_size} 字节，预期 {expected_size} 字节")

                    if actual_size < 2048: # Small file HTML check
                        with open(part_file, 'rb') as f:
                            head = f.read(150)
                            if b'<html' in head.lower() or b'<!doctype' in head.lower():
                                raise Exception("下载的文件为 HTML 网页并非有效文件，可能被网盘拦截。")

                    download_success = True
                    break
                except Exception as dl_err:
                    last_download_error = dl_err
                    logger.warning("Download attempt %d/%d failed for %s: %s", attempt, max_retries, fname, dl_err)
                    part_file.unlink(missing_ok=True)
                    if attempt < max_retries:
                        time.sleep(2)
                    continue

            if not download_success:
                raise Exception(f"下载失败 (已重试 {max_retries} 次): {str(last_download_error)}")

            # Rename .part to final file atomically
            os.replace(part_file, local_file)
            self.progress = 100.0

            # 4. Extract & Organize
            if cfg.get("auto_extract", True):
                self.status = "EXTRACTING"
                if progress_callback:
                    progress_callback(self)

                dest_dir = safe_join(lib_root, safe_filename(self.author), safe_filename(self.month))
                passwords = [self.password, "f95zone", self.author]
                ok, msg = extract_archive(local_file, dest_dir, passwords=passwords)
                if not ok:
                    raise Exception(f"解压失败: {msg}")

                self.final_path = str(dest_dir)

                if cfg.get("delete_archive_after_extract", True):
                    try:
                        local_file.unlink(missing_ok=True)
                    except Exception as del_err:
                        logger.warning("Failed to remove archive %s after extract: %s", local_file, del_err)

            self.status = "COMPLETED"
            if progress_callback:
                progress_callback(self)

        except Exception as e:
            logger.error("DownloadJob error for %s (%s): %s", self.author, self.month, e)
            try:
                if 'part_file' in locals() and part_file.exists():
                    part_file.unlink(missing_ok=True)
            except Exception as part_err:
                logger.debug("Failed to clean up part file on error: %s", part_err)
            self.status = "FAILED"
            self.error_msg = str(e)
            if progress_callback:
                progress_callback(self)
