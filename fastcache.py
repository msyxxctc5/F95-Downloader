import os
import time
import threading
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

import scanner

logger = logging.getLogger("fastcache")

STATE: Dict[str, Any] = {
    "running": False,
    "checked": 0,
    "total": 0,
    "updated": [],
    "online": True
}

_bg_lock = threading.Lock()

def _entry_ok(e: Any, root: Path) -> bool:
    return (
        isinstance(e, dict)
        and e.get("v") == scanner.CACHE_VERSION
        and e.get("root") == str(root)
    )

def _author_names(root: Path) -> List[str]:
    try:
        with os.scandir(root) as it:
            return sorted(e.name for e in it if e.is_dir() and not e.name.startswith("."))
    except Exception as e:
        logger.warning(f"Failed to scan author directories in {root}: {e}")
        return []

def refresh_author(root: Path, name: str, force: bool = False, save: bool = True) -> bool:
    """
    Refreshes cache for a single author.
    Heavy file-system inspection (get_dir_signature and scan_author_directory)
    is performed strictly outside _cache_lock to prevent blocking concurrent requests.
    Returns True if author was re-scanned/updated, False if cached signature matched.
    """
    p = root / name
    if not p.exists() or not p.is_dir():
        return False

    sig = scanner.get_dir_signature(p)

    with scanner._cache_lock:
        cache = scanner.load_library_cache()
        entry = cache.get(name)
        if not force and _entry_ok(entry, root) and entry.get("sig") == sig:
            return False

    data = scanner.scan_author_directory(p)

    with scanner._cache_lock:
        cache = scanner.load_library_cache()
        cache[name] = {
            "v": scanner.CACHE_VERSION,
            "root": str(root),
            "sig": sig,
            "data": data
        }
        if save:
            scanner.save_library_cache(cache)
    return True

def list_cached(root_dir: str) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Instantly returns author list using cached metadata.
    Does NOT inspect subdirectories or calculate deep signatures for known authors.
    Only newly discovered authors are scanned immediately.
    Returns: (authors_list, is_online)
    """
    root = Path(root_dir)
    if not root.exists():
        STATE["online"] = False
        with scanner._cache_lock:
            cache = scanner.load_library_cache()
            offline_results = [
                dict(e["data"])
                for n, e in sorted(cache.items())
                if isinstance(e, dict) and e.get("root") == str(root)
            ]
            return offline_results, False

    STATE["online"] = True
    names = _author_names(root)

    with scanner._cache_lock:
        cache = scanner.load_library_cache()
        known = {
            n for n, e in cache.items()
            if _entry_ok(e, root)
        }

    # Only scan brand new authors that have never been cached
    for n in names:
        if n not in known:
            refresh_author(root, n, force=True, save=False)

    with scanner._cache_lock:
        cache = scanner.load_library_cache()
        names_set = set(names)
        # Evict deleted authors belonging to this root
        for n in [n for n, e in cache.items() if isinstance(e, dict) and e.get("root") == str(root) and n not in names_set]:
            del cache[n]
        scanner.save_library_cache(cache)
        results = [dict(cache[n]["data"]) for n in names if n in cache]
        return results, True

def revalidate_all(root_dir: str, throttle: float = 0.03):
    """
    Background worker that checks signatures author-by-author with gentle throttling.
    """
    root = Path(root_dir)
    if not root.exists():
        STATE.update(running=False, online=False)
        return

    names = _author_names(root)
    STATE.update(running=True, checked=0, total=len(names), updated=[], online=True)

    try:
        for n in names:
            if not STATE["running"]:
                break
            if refresh_author(root, n, force=False, save=False):
                STATE["updated"].append(n)
            STATE["checked"] += 1
            if throttle > 0:
                time.sleep(throttle)

        if STATE["updated"]:
            with scanner._cache_lock:
                scanner.save_library_cache(scanner.load_library_cache())
            logger.info(f"Background revalidation completed: {len(STATE['updated'])} authors updated: {STATE['updated']}")
    except Exception as e:
        logger.error(f"Error during background revalidation: {e}")
    finally:
        STATE["running"] = False

def start_background_revalidate(root_dir: str):
    """
    Starts background revalidation if not already running.
    """
    with _bg_lock:
        if not STATE["running"]:
            STATE["running"] = True
            threading.Thread(target=revalidate_all, args=(root_dir,), daemon=True).start()
