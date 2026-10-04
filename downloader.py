import os
import re
import time
import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional, Tuple

from config import load_config, get_request_cookies
from diff_engine import unmask_f95_link
from extractor import extract_archive

def resolve_direct_download_url(real_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Given a cloud drive URL, resolve it to direct downloadable stream URL and filename.
    Returns: (download_url, filename)
    """
    # 1. Pixeldrain
    px_match = re.search(r'pixeldrain\.com/u/([a-zA-Z0-9]+)', real_url)
    if px_match:
        file_id = px_match.group(1)
        try:
            info_res = requests.get(f"https://pixeldrain.com/api/file/{file_id}/info", timeout=10)
            if info_res.status_code == 200:
                data = info_res.json()
                fname = data.get("name", f"pixeldrain_{file_id}.zip")
                dl_url = f"https://pixeldrain.com/api/file/{file_id}"
                return dl_url, fname
        except Exception:
            return f"https://pixeldrain.com/api/file/{file_id}", f"pixeldrain_{file_id}.zip"

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
        dl_dir = Path(cfg.get("download_dir", r"c:\Users\Despa\Desktop\Dev\downloads"))
        dl_dir.mkdir(parents=True, exist_ok=True)
        lib_root = Path(cfg.get("library_root", r"H:\akinaclub"))

        try:
            # 1. Unmask link
            self.status = "UNMASKING"
            if progress_callback:
                progress_callback(self)

            real_url = unmask_f95_link(self.masked_url, cookies)
            if not real_url:
                raise Exception("无法解析 F95zone 反代跳转链接")
            self.real_url = real_url

            # 2. Check if host supports direct backend downloading
            direct_url, fname = resolve_direct_download_url(real_url)
            if not direct_url:
                raise Exception(f"该网盘不支持后台直接下载 (如 Mega/Workupload 需浏览器客户端)，请点击「在浏览器中打开网盘」进行下载: {real_url}")

            from config import safe_join, safe_filename

            if not fname:
                fname = f"{safe_filename(self.author)}_{safe_filename(self.month)}.zip"
            else:
                fname = safe_filename(fname)

            local_file = safe_join(dl_dir, fname)
            part_file = local_file.with_name(f"{local_file.name}.part")

            # 3. Download stream to .part file first
            self.status = "DOWNLOADING"
            if progress_callback:
                progress_callback(self)

            headers = {'User-Agent': 'Mozilla/5.0'}
            with requests.get(direct_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                
                # Check Content-Type to prevent saving HTML error pages
                content_type = r.headers.get('content-type', '').lower()
                if 'text/html' in content_type:
                    raise Exception(f"网盘返回了 HTML 验证页面而非文件内容，请在浏览器中打开网盘下载: {real_url}")

                total_length = r.headers.get('content-length')
                if total_length is None:
                    self.total_size = 0
                else:
                    self.total_size = int(total_length)

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

            # Verification of downloaded file
            if part_file.stat().st_size < 10000: # < 10KB
                with open(part_file, 'rb') as f:
                    head = f.read(100)
                    if b'<html' in head.lower() or b'<!doctype' in head.lower():
                        part_file.unlink(missing_ok=True)
                        raise Exception("下载的文件为 HTML 网页并非压缩包，请在浏览器中手动下载。")

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
                    except Exception:
                        pass

            self.status = "COMPLETED"
            if progress_callback:
                progress_callback(self)

        except Exception as e:
            try:
                if 'part_file' in locals() and part_file.exists():
                    part_file.unlink(missing_ok=True)
            except Exception:
                pass
            self.status = "FAILED"
            self.error_msg = str(e)
            if progress_callback:
                progress_callback(self)
