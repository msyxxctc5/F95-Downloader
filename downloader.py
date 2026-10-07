import os
import re
import time
import logging
import threading
import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional, Tuple, List, Set

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
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()

    def pause(self):
        self.status = "PAUSED"
        self._pause_event.set()

    def resume(self):
        self._pause_event.clear()
        self._cancel_event.clear()
        self.status = "PENDING"
        self.error_msg = ""
        self.speed_str = "0 KB/s"

    def cancel(self):
        self.status = "CANCELLED"
        self._cancel_event.set()

    def run(self, progress_callback: Optional[Callable[['DownloadJob'], None]] = None):
        cfg = load_config()
        cookies = get_request_cookies()
        dl_dir = get_download_dir()
        dl_dir.mkdir(parents=True, exist_ok=True)
        lib_root = get_library_root()

        try:
            if self._cancel_event.is_set() or self.status == "CANCELLED":
                return
            if self._pause_event.is_set() or self.status == "PAUSED":
                return

            # 1. Unmask link with rate limiting (if not already unmasked)
            if not self.real_url:
                self.status = "UNMASKING"
                if progress_callback:
                    progress_callback(self)

                real_url, unmask_err = rate_limited_unmask(self.masked_url, cookies)
                if not real_url:
                    err_detail = unmask_err or "无法解析 F95zone 反代跳转链接"
                    logger.warning("Unmask failed for job %s_%s: %s", self.author, self.month, err_detail)
                    raise Exception(err_detail)
                self.real_url = real_url
            else:
                real_url = self.real_url

            if self._cancel_event.is_set() or self.status == "CANCELLED":
                return
            if self._pause_event.is_set() or self.status == "PAUSED":
                return

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

            # 3. Download stream to .part file with Range support, retry and integrity check
            self.status = "DOWNLOADING"
            if progress_callback:
                progress_callback(self)

            max_retries = 3
            last_download_error = None
            download_success = False

            for attempt in range(1, max_retries + 1):
                if self._cancel_event.is_set() or self.status == "CANCELLED":
                    part_file.unlink(missing_ok=True)
                    return
                if self._pause_event.is_set() or self.status == "PAUSED":
                    return

                try:
                    resume_from = part_file.stat().st_size if part_file.exists() else 0
                    headers = {'User-Agent': get_user_agent()}
                    if resume_from > 0:
                        headers['Range'] = f"bytes={resume_from}-"

                    with requests.get(direct_url, headers=headers, stream=True, timeout=35) as r:
                        if r.status_code == 416:
                            # Range not satisfiable, reset .part file and retry from byte 0
                            logger.warning("Range 416 received for %s, resetting .part file", fname)
                            part_file.unlink(missing_ok=True)
                            resume_from = 0
                            raise Exception("续传偏移无效 (HTTP 416)，已重置并重新下载")

                        r.raise_for_status()

                        # Check Content-Type to prevent saving HTML error pages
                        content_type = r.headers.get('content-type', '').lower()
                        if 'text/html' in content_type:
                            raise Exception(f"网盘返回了 HTML 验证页面而非文件内容，请在浏览器中打开网盘下载: {real_url}")

                        if r.status_code == 206:
                            mode = 'ab'
                            cr = r.headers.get('content-range', '')
                            if '/' in cr:
                                total_part = cr.split('/')[-1].strip()
                                expected_size = int(total_part) if total_part.isdigit() else 0
                            else:
                                expected_size = 0
                        else:
                            mode = 'wb'
                            resume_from = 0
                            cl = r.headers.get('content-length')
                            expected_size = int(cl) if cl and cl.isdigit() else 0

                        self.total_size = expected_size
                        downloaded = resume_from
                        self.downloaded_size = downloaded
                        if self.total_size > 0:
                            self.progress = round((downloaded / self.total_size) * 100, 1)

                        start_time = time.time()
                        last_time = start_time
                        last_bytes = downloaded

                        with open(part_file, mode) as f:
                            for chunk in r.iter_content(chunk_size=1024 * 512):
                                if self._cancel_event.is_set() or self.status == "CANCELLED":
                                    logger.info("Download cancelled: %s", fname)
                                    f.flush()
                                    f.close()
                                    part_file.unlink(missing_ok=True)
                                    self.status = "CANCELLED"
                                    self.speed_str = "0 KB/s"
                                    if progress_callback:
                                        progress_callback(self)
                                    return

                                if self._pause_event.is_set() or self.status == "PAUSED":
                                    logger.info("Download paused: %s at %d bytes", fname, downloaded)
                                    f.flush()
                                    self.status = "PAUSED"
                                    self.speed_str = "0 KB/s"
                                    if progress_callback:
                                        progress_callback(self)
                                    return

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
                                part_file.unlink(missing_ok=True)
                                raise Exception("下载的文件为 HTML 网页并非有效文件，可能被网盘拦截。")

                    download_success = True
                    break
                except Exception as dl_err:
                    if self.status in ("PAUSED", "CANCELLED"):
                        return
                    last_download_error = dl_err
                    logger.warning("Download attempt %d/%d failed for %s: %s", attempt, max_retries, fname, dl_err)
                    # Preserve .part file on transient errors for subsequent resume
                    if attempt < max_retries:
                        time.sleep(2)
                    continue

            if self.status in ("PAUSED", "CANCELLED"):
                return

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
            if self.status in ("PAUSED", "CANCELLED"):
                return
            logger.error("DownloadJob error for %s (%s): %s", self.author, self.month, e)
            self.status = "FAILED"
            self.error_msg = str(e)
            self.speed_str = "0 KB/s"
            if progress_callback:
                progress_callback(self)


class DownloadQueueManager:
    """
    Manages concurrent download execution and waiting queue (FIFO).
    Guarantees that at most max_concurrent tasks are actively downloading/extracting/unmasking.
    Excess tasks enter QUEUED state and automatically start when running tasks finish, pause, or cancel.
    """
    def __init__(self, max_concurrent: int = 3, jobs_dict: Optional[Dict[str, DownloadJob]] = None):
        self._max_concurrent = max(1, min(5, int(max_concurrent)))
        self._jobs: Dict[str, DownloadJob] = jobs_dict if jobs_dict is not None else {}
        self._queue: List[str] = []
        self._running: Set[str] = set()
        self._lock = threading.RLock()

    @property
    def jobs(self) -> Dict[str, DownloadJob]:
        return self._jobs

    def get_max_concurrent(self) -> int:
        with self._lock:
            return self._max_concurrent

    def set_max_concurrent(self, limit: int):
        with self._lock:
            self._max_concurrent = max(1, min(5, int(limit)))
            self._process_queue()

    def get_queue_position(self, job_id: str) -> Optional[int]:
        with self._lock:
            if job_id in self._queue:
                return self._queue.index(job_id) + 1
            return None

    def _clean_stale_running(self):
        stale = [
            jid for jid in self._running
            if jid not in self._jobs or self._jobs[jid].status in ("COMPLETED", "DONE", "FAILED", "CANCELLED", "PAUSED")
        ]
        for jid in stale:
            self._running.discard(jid)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            self._clean_stale_running()
            return {
                "running_count": len(self._running),
                "queued_count": len(self._queue),
                "max_concurrent": self._max_concurrent
            }

    def submit(self, job_id: str, job: DownloadJob) -> str:
        with self._lock:
            self._clean_stale_running()
            if job_id in self._jobs:
                curr = self._jobs[job_id].status
                if curr in ("DOWNLOADING", "EXTRACTING", "UNMASKING", "PENDING"):
                    return "already_running"
                if curr == "QUEUED":
                    return "already_queued"
                if curr == "PAUSED":
                    return self.resume(job_id)

            self._jobs[job_id] = job

            if len(self._running) < self._max_concurrent:
                self._running.add(job_id)
                job.status = "PENDING"
                self._spawn_worker(job_id, job)
                return "started"
            else:
                job.status = "QUEUED"
                if job_id not in self._queue:
                    self._queue.append(job_id)
                return "queued"

    def resume(self, job_id: str) -> str:
        with self._lock:
            self._clean_stale_running()
            job = self._jobs.get(job_id)
            if not job:
                return "not_found"
            if job.status in ("DOWNLOADING", "EXTRACTING", "UNMASKING"):
                return "already_running"
            if job.status == "QUEUED":
                return "already_queued"

            job.resume()
            if len(self._running) < self._max_concurrent:
                self._running.add(job_id)
                job.status = "PENDING"
                self._spawn_worker(job_id, job)
                return "resumed"
            else:
                job.status = "QUEUED"
                if job_id not in self._queue:
                    self._queue.append(job_id)
                return "queued"

    def pause(self, job_id: str) -> str:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return "not_found"

            if job_id in self._queue:
                self._queue.remove(job_id)
                job.pause()
                return "paused"

            job.pause()
            return "paused"

    def pause_all(self) -> int:
        with self._lock:
            self._clean_stale_running()
            count = 0
            # Drain queue and mark each as paused
            while self._queue:
                jid = self._queue.pop(0)
                job = self._jobs.get(jid)
                if job:
                    job.pause()
                    count += 1
            # Signal pause to all currently running jobs
            for jid in list(self._running):
                job = self._jobs.get(jid)
                if job:
                    job.pause()
                    count += 1
            return count

    def resume_all(self) -> int:
        with self._lock:
            self._clean_stale_running()
            count = 0
            paused_jids = [
                jid for jid, job in self._jobs.items()
                if job.status == "PAUSED"
            ]
            for jid in paused_jids:
                self.resume(jid)
                count += 1
            return count

    def cancel(self, job_id: str) -> str:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return "not_found"

            if job_id in self._queue:
                self._queue.remove(job_id)

            job.cancel()
            return "cancelled"

    def clear_finished(self):
        with self._lock:
            self._clean_stale_running()
            to_remove = [
                k for k, v in self._jobs.items()
                if v.status in ("COMPLETED", "DONE", "FAILED", "CANCELLED")
                and k not in self._running
                and k not in self._queue
            ]
            for k in to_remove:
                del self._jobs[k]

    def _spawn_worker(self, job_id: str, job: DownloadJob):
        def _worker():
            try:
                job.run()
            except Exception as e:
                logger.error("Job %s worker failed: %s", job_id, e)
            finally:
                with self._lock:
                    self._running.discard(job_id)
                    self._process_queue()

        t = threading.Thread(target=_worker, daemon=True, name=f"DownloadWorker-{job_id}")
        t.start()

    def _process_queue(self):
        # Must be called within self._lock
        self._clean_stale_running()
        while len(self._running) < self._max_concurrent and self._queue:
            next_id = self._queue.pop(0)
            next_job = self._jobs.get(next_id)
            if not next_job:
                continue
            if next_job.status in ("CANCELLED", "COMPLETED", "DONE", "PAUSED"):
                continue
            next_job.status = "PENDING"
            self._running.add(next_id)
            self._spawn_worker(next_id, next_job)

