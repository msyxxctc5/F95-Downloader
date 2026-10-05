import os
import re
from pathlib import Path
from typing import Dict, List, Set, Any

MONTH_NAME_MAP = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12',
    'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
    'jun': '06', 'jul': '07', 'aug': '08', 'sep': '09',
    'oct': '10', 'nov': '11', 'dec': '12'
}

# Sort month names by length descending so fuller names (e.g. 'january') match before abbreviations ('jan')
SORTED_MONTH_NAMES = sorted(MONTH_NAME_MAP.keys(), key=len, reverse=True)

def normalize_month(text: str) -> str:
    """
    Standardize various date/month representations into 'YYYY-MM'.
    Examples:
      - '2020.01' -> '2020-01'
      - '2020 04' -> '2020-04'
      - '202103'  -> '2021-03'
      - '2021-03' -> '2021-03'
      - 'March 2021' -> '2021-03'
      - '2021 March' -> '2021-03'
    """
    text = text.strip()
    
    # 1. Matches like 2021.03, 2021-03, 2021 03, 2021_03 (YYYY first)
    m1 = re.search(r'((?:19|20)\d{2})[.\-_\s/](0?[1-9]|1[0-2])(?!\d)', text)
    if m1:
        year, month = m1.group(1), int(m1.group(2))
        return f"{year}-{month:02d}"

    # 1b. Matches like 03-2019, 04/2019, 10-2020 (MM first)
    m1b = re.search(r'(?<!\d)(0?[1-9]|1[0-2])[.\-_\s/]((?:19|20)\d{2})', text)
    if m1b:
        month, year = int(m1b.group(1)), m1b.group(2)
        return f"{year}-{month:02d}"
        
    # 2. Matches like 202004, 202103 (6 digits)
    m2 = re.search(r'((?:19|20)\d{2})(0[1-9]|1[0-2])(?!\d)', text)
    if m2:
        year, month = m2.group(1), int(m2.group(2))
        return f"{year}-{month:02d}"

    # 3. Matches like March 2021 or 2021 March (requires exact word boundary \b)
    lower = text.lower()
    for mname in SORTED_MONTH_NAMES:
        if re.search(rf'\b{re.escape(mname)}\b', lower):
            myear = re.search(r'((?:19|20)\d{2})', text)
            if myear:
                return f"{myear.group(1)}-{MONTH_NAME_MAP[mname]}"
                
    return ""

IGNORE_EXTENSIONS = {
    '.txt', '.nfo', '.url', '.lnk', '.ini', '.db', '.ds_store', '.part',
    '.tmp', '.log', '.md', '.html', '.htm', '.json', '.xml', '.yml', '.yaml'
}

def is_dir_non_empty(d: Path) -> bool:
    """Returns True if directory contains at least one non-ignored file."""
    try:
        for f in d.rglob('*'):
            if f.is_file() and not f.name.startswith('.') and f.suffix.lower() not in IGNORE_EXTENSIONS:
                return True
    except Exception:
        pass
    return False

def scan_author_directory(author_dir: Path) -> Dict[str, Any]:
    """
    Scans a single author directory and returns detected months, terms, media assets, and structure.
    Filters out non-media garbage (.txt, .nfo, etc.) to prevent false positives.
    """
    detected_months: Set[str] = set()
    detected_years: Set[str] = set()
    detected_terms: Set[str] = set()
    media_assets: List[Dict[str, Any]] = []
    month_details: Dict[str, List[str]] = {}
    total_size = 0
    file_count = 0

    if not author_dir.exists() or not author_dir.is_dir():
        return {
            "name": author_dir.name,
            "path": str(author_dir),
            "months": [],
            "years": [],
            "terms": [],
            "media_assets": [],
            "all_names": [],
            "error": "Directory does not exist"
        }

    try:
        entries = list(author_dir.iterdir())
    except Exception as e:
        return {
            "name": author_dir.name,
            "path": str(author_dir),
            "months": [],
            "years": [],
            "terms": [],
            "media_assets": [],
            "all_names": [],
            "error": str(e)
        }

    for entry in entries:
        if entry.name.startswith('.'):
            continue
        try:
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in IGNORE_EXTENSIONS:
                    continue
                file_count += 1
                sz = entry.stat().st_size
                total_size += sz
                
                # Check Month
                m = normalize_month(entry.name)
                if m:
                    detected_months.add(m)
                    month_details.setdefault(m, []).append(entry.name)
                # Check Term
                t_match = re.search(r'(Term\s*\d+|Pack\s*\d+|Vol(?:ume)?\.?\s*\d+)', entry.name, re.I)
                if t_match:
                    detected_terms.add(t_match.group(1).title())

                media_assets.append({
                    "name": entry.name,
                    "rel_path": entry.name,
                    "is_dir": False,
                    "size_mb": round(sz / (1024 * 1024), 2)
                })

            elif entry.is_dir():
                has_content = is_dir_non_empty(entry)
                # Direct subfolder month match (e.g. "2020.01", "202103") - requires actual content
                m = normalize_month(entry.name)
                if m and has_content:
                    detected_months.add(m)
                    month_details.setdefault(m, []).append(entry.name)
                # Check Term
                t_match = re.search(r'(Term\s*\d+|Pack\s*\d+|Vol(?:ume)?\.?\s*\d+)', entry.name, re.I)
                if t_match and has_content:
                    detected_terms.add(t_match.group(1).title())

                if has_content:
                    media_assets.append({
                        "name": entry.name,
                        "rel_path": entry.name,
                        "is_dir": True,
                        "size_mb": 0
                    })

                # Year folder detection & transparency (e.g. "2021", "2022")
                year_match = re.fullmatch(r'((?:19|20)\d{2})', entry.name.strip())
                if year_match and has_content:
                    year = year_match.group(1)
                    has_sub_months = False
                    for sub_entry in entry.iterdir():
                        if sub_entry.name.startswith('.'):
                            continue
                        sub_m = re.fullmatch(r'(0?[1-9]|1[0-2])', sub_entry.name.strip())
                        if sub_m:
                            norm_m = f"{year}-{int(sub_m.group(1)):02d}"
                            if (sub_entry.is_file() and sub_entry.suffix.lower() not in IGNORE_EXTENSIONS) or (sub_entry.is_dir() and is_dir_non_empty(sub_entry)):
                                detected_months.add(norm_m)
                                month_details.setdefault(norm_m, []).append(f"{entry.name}/{sub_entry.name}")
                                has_sub_months = True
                        else:
                            if sub_entry.is_file() and sub_entry.suffix.lower() not in IGNORE_EXTENSIONS:
                                media_assets.append({
                                    "name": sub_entry.name,
                                    "rel_path": f"{entry.name}/{sub_entry.name}",
                                    "is_dir": False,
                                    "size_mb": round(sub_entry.stat().st_size / (1024 * 1024), 2)
                                })
                            elif sub_entry.is_dir() and is_dir_non_empty(sub_entry):
                                media_assets.append({
                                    "name": sub_entry.name,
                                    "rel_path": f"{entry.name}/{sub_entry.name}",
                                    "is_dir": True,
                                    "size_mb": 0
                                })
                    if not has_sub_months:
                        detected_years.add(year)
                else:
                    # Index sub-entries up to 2 levels deep
                    try:
                        for sub in entry.iterdir():
                            if sub.name.startswith('.'):
                                continue
                            if sub.is_file():
                                if sub.suffix.lower() not in IGNORE_EXTENSIONS:
                                    media_assets.append({
                                        "name": sub.name,
                                        "rel_path": f"{entry.name}/{sub.name}",
                                        "is_dir": False,
                                        "size_mb": round(sub.stat().st_size / (1024 * 1024), 2)
                                    })
                            elif sub.is_dir():
                                media_assets.append({
                                    "name": sub.name,
                                    "rel_path": f"{entry.name}/{sub.name}",
                                    "is_dir": True,
                                    "size_mb": 0
                                })
                                for sub2 in sub.iterdir():
                                    if sub2.is_file() and sub2.suffix.lower() not in IGNORE_EXTENSIONS:
                                        media_assets.append({
                                            "name": sub2.name,
                                            "rel_path": f"{entry.name}/{sub.name}/{sub2.name}",
                                            "is_dir": False,
                                            "size_mb": round(sub2.stat().st_size / (1024 * 1024), 2)
                                        })
                    except Exception:
                        pass
        except Exception:
            continue

    sorted_months = sorted(list(detected_months))
    sorted_years = sorted(list(detected_years))
    sorted_terms = sorted(list(detected_terms))

    # Detect dominant archive style
    if len(sorted_months) >= 3:
        style = "MONTHLY"
    elif len(sorted_years) >= 2:
        style = "YEARLY"
    elif len(sorted_terms) >= 3:
        style = "TERMS"
    else:
        style = "STANDALONE_WORKS"

    return {
        "name": author_dir.name,
        "path": str(author_dir),
        "archive_style": style,
        "months": sorted_months,
        "years": sorted_years,
        "terms": sorted_terms,
        "latest_month": sorted_months[-1] if sorted_months else (sorted_years[-1] if sorted_years else None),
        "latest_year": sorted_years[-1] if sorted_years else None,
        "month_count": len(sorted_months),
        "year_count": len(sorted_years),
        "term_count": len(sorted_terms),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "file_count": file_count,
        "media_assets": media_assets,
        "all_names": list({a["name"].lower() for a in media_assets})
    }

import threading
import json
import logging

logger = logging.getLogger("scanner")

CACHE_VERSION = 2
CACHE_DIR = Path(__file__).parent / "data"
CACHE_FILE = CACHE_DIR / "library_cache.json"
_memory_cache: Dict[str, Any] = {}
_cache_lock = threading.RLock()

from config import atomic_write_json

def get_dir_signature(p: Path) -> float:
    """
    Computes a fast modification signature using directory and sub-directory st_mtime up to 2 levels deep.
    """
    try:
        sig = p.stat().st_mtime
        for sub in p.iterdir():
            if sub.is_dir():
                m = sub.stat().st_mtime
                if m > sig:
                    sig = m
                try:
                    for sub2 in sub.iterdir():
                        if sub2.is_dir():
                            m2 = sub2.stat().st_mtime
                            if m2 > sig:
                                sig = m2
                except Exception:
                    pass
        return sig
    except Exception:
        return 0.0

def load_library_cache() -> Dict[str, Any]:
    global _memory_cache
    with _cache_lock:
        if _memory_cache:
            return _memory_cache
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    _memory_cache = json.load(f)
                    return _memory_cache
            except Exception as e:
                logger.warning(f"Failed to read library_cache.json, resetting cache: {e}")
                _memory_cache = {}
        return _memory_cache

def save_library_cache(cache: Dict[str, Any]):
    global _memory_cache
    with _cache_lock:
        _memory_cache = cache
        try:
            atomic_write_json(CACHE_FILE, cache)
        except Exception as e:
            logger.error(f"Failed to save library cache atomically: {e}")

def invalidate_author_cache(author_name: str):
    global _memory_cache
    with _cache_lock:
        cache = load_library_cache()
        if author_name in cache:
            del cache[author_name]
            save_library_cache(cache)

def scan_author_directory_cached(author_dir: Path, force: bool = False) -> Dict[str, Any]:
    """
    Retrieves author data from cache if directory signature hasn't changed.
    Performs directory inspection outside the lock to avoid contention.
    Returns a copy of the data dictionary to avoid cache contamination.
    """
    name = author_dir.name
    root_str = str(author_dir.parent)
    sig = get_dir_signature(author_dir)

    with _cache_lock:
        cache = load_library_cache()
        if not force and name in cache:
            entry = cache[name]
            if entry.get("v") == CACHE_VERSION and entry.get("root") == root_str and entry.get("sig") == sig:
                return dict(entry["data"])

    fresh_data = scan_author_directory(author_dir)
    with _cache_lock:
        cache = load_library_cache()
        cache[name] = {"v": CACHE_VERSION, "root": root_str, "sig": sig, "data": fresh_data}
        save_library_cache(cache)
        return dict(fresh_data)

def scan_all_authors(root_dir: str = r"H:\akinaclub", force: bool = False) -> List[Dict[str, Any]]:
    """
    Scans the entire library root directory for all authors using mtime-signature caching.
    If directory mtime has not changed, zero deep disk I/O is performed.
    Returns safe copies of author data to avoid mutation of cache entries.
    """
    root = Path(root_dir)
    if not root.exists():
        return []
        
    root_str = str(root)
    with _cache_lock:
        cache = load_library_cache()
        results = []
        has_changes = False
        current_names = set()

        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir() and not entry.name.startswith('.'):
                name = entry.name
                current_names.add(name)
                sig = get_dir_signature(entry)

                if not force and name in cache:
                    cached_entry = cache[name]
                    if cached_entry.get("v") == CACHE_VERSION and cached_entry.get("root") == root_str and cached_entry.get("sig") == sig:
                        results.append(dict(cached_entry["data"]))
                        continue

                data = scan_author_directory(entry)
                cache[name] = {"v": CACHE_VERSION, "root": root_str, "sig": sig, "data": data}
                results.append(dict(data))
                has_changes = True

        # Evict deleted directories from cache belonging to this root
        for stale, e in list(cache.items()):
            if isinstance(e, dict) and e.get("root") == root_str and stale not in current_names:
                del cache[stale]
                has_changes = True

        if has_changes:
            save_library_cache(cache)
                
        return results

if __name__ == "__main__":
    import time
    print("Testing cached scanning on H:\\akinaclub...")
    t0 = time.time()
    res1 = scan_all_authors()
    t1 = time.time()
    print(f"First run (populate/check cache): {len(res1)} authors scanned in {t1 - t0:.3f}s")

    t2 = time.time()
    res2 = scan_all_authors()
    t3 = time.time()
    print(f"Second run (100% cache hit): {len(res2)} authors verified in {t3 - t2:.3f}s")

