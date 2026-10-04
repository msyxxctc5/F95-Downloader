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
    m1 = re.search(r'(20\d{2})[.\-_\s/](0?[1-9]|1[0-2])(?!\d)', text)
    if m1:
        year, month = m1.group(1), int(m1.group(2))
        return f"{year}-{month:02d}"

    # 1b. Matches like 03-2019, 04/2019, 10-2020 (MM first)
    m1b = re.search(r'(?<!\d)(0?[1-9]|1[0-2])[.\-_\s/](20\d{2})', text)
    if m1b:
        month, year = int(m1b.group(1)), m1b.group(2)
        return f"{year}-{month:02d}"
        
    # 2. Matches like 202004, 202103 (6 digits)
    m2 = re.search(r'(20\d{2})(0[1-9]|1[0-2])(?!\d)', text)
    if m2:
        year, month = m2.group(1), int(m2.group(2))
        return f"{year}-{month:02d}"

    # 3. Matches like March 2021 or 2021 March
    lower = text.lower()
    for mname, mnum in MONTH_NAME_MAP.items():
        if mname in lower:
            myear = re.search(r'(20\d{2})', text)
            if myear:
                return f"{myear.group(1)}-{mnum}"
                
    return ""

def scan_author_directory(author_dir: Path) -> Dict[str, Any]:
    """
    Scans a single author directory and returns detected months, files, and structure.
    """
    detected_months: Set[str] = set()
    month_details: Dict[str, List[str]] = {}
    other_items: List[str] = []
    total_size = 0
    file_count = 0

    if not author_dir.exists() or not author_dir.is_dir():
        return {
            "name": author_dir.name,
            "path": str(author_dir),
            "months": [],
            "error": "Directory does not exist"
        }

    try:
        entries = list(author_dir.iterdir())
    except Exception as e:
        return {
            "name": author_dir.name,
            "path": str(author_dir),
            "months": [],
            "error": str(e)
        }

    all_names: List[str] = []
    for entry in entries:
        try:
            all_names.append(entry.name.lower())
            if entry.is_file():
                file_count += 1
                total_size += entry.stat().st_size
                m = normalize_month(entry.name)
                if m:
                    detected_months.add(m)
                    month_details.setdefault(m, []).append(entry.name)
                else:
                    other_items.append(entry.name)
            elif entry.is_dir():
                # Direct subfolder month match (e.g. "2020.01", "202103")
                m = normalize_month(entry.name)
                if m:
                    detected_months.add(m)
                    month_details.setdefault(m, []).append(entry.name)
                else:
                    # Check if it's a year folder (e.g. "2021", "2022")
                    year_match = re.fullmatch(r'20\d{2}', entry.name.strip())
                    if year_match:
                        year = year_match.group(0)
                        # Check sub-month directories inside year folder (e.g. 01, 02, 1, 2)
                        for sub_entry in entry.iterdir():
                            all_names.append(sub_entry.name.lower())
                            sub_month = re.fullmatch(r'(0?[1-9]|1[0-2])', sub_entry.name.strip())
                            if sub_month:
                                sub_m = f"{year}-{int(sub_month.group(1)):02d}"
                                detected_months.add(sub_m)
                                month_details.setdefault(sub_m, []).append(f"{entry.name}/{sub_entry.name}")
                            else:
                                other_items.append(f"{entry.name}/{sub_entry.name}")
                    else:
                        other_items.append(entry.name)
                # Index sub-entries up to 2 levels deep (avoids freezing on huge image sequences)
                try:
                    for sub in entry.iterdir():
                        all_names.append(sub.name.lower())
                        if sub.is_dir():
                            for sub2 in sub.iterdir():
                                all_names.append(sub2.name.lower())
                except Exception:
                    pass
        except Exception:
            continue

    sorted_months = sorted(list(detected_months))
    return {
        "name": author_dir.name,
        "path": str(author_dir),
        "months": sorted_months,
        "latest_month": sorted_months[-1] if sorted_months else None,
        "month_count": len(sorted_months),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "file_count": file_count,
        "other_items_sample": other_items[:5],
        "all_names": list(set(all_names))
    }

import json

CACHE_DIR = Path(__file__).parent / "data"
CACHE_FILE = CACHE_DIR / "library_cache.json"
_memory_cache: Dict[str, Any] = {}

def get_dir_signature(p: Path) -> float:
    """
    Computes a fast modification signature using directory and sub-directory st_mtime.
    Requires no recursive deep scanning.
    """
    try:
        sig = p.stat().st_mtime
        for sub in p.iterdir():
            if sub.is_dir():
                m = sub.stat().st_mtime
                if m > sig:
                    sig = m
        return sig
    except Exception:
        return 0.0

def load_library_cache() -> Dict[str, Any]:
    global _memory_cache
    if _memory_cache:
        return _memory_cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _memory_cache = json.load(f)
                return _memory_cache
        except Exception:
            _memory_cache = {}
    return _memory_cache

def save_library_cache(cache: Dict[str, Any]):
    global _memory_cache
    _memory_cache = cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def invalidate_author_cache(author_name: str):
    global _memory_cache
    cache = load_library_cache()
    if author_name in cache:
        del cache[author_name]
        save_library_cache(cache)

def scan_author_directory_cached(author_dir: Path, force: bool = False) -> Dict[str, Any]:
    """
    Retrieves author data from cache if directory signature hasn't changed.
    """
    cache = load_library_cache()
    name = author_dir.name
    sig = get_dir_signature(author_dir)

    if not force and name in cache and cache[name].get("sig") == sig:
        return cache[name]["data"]

    fresh_data = scan_author_directory(author_dir)
    cache[name] = {"sig": sig, "data": fresh_data}
    save_library_cache(cache)
    return fresh_data

def scan_all_authors(root_dir: str = r"H:\akinaclub", force: bool = False) -> List[Dict[str, Any]]:
    """
    Scans the entire library root directory for all authors using mtime-signature caching.
    If directory mtime has not changed, zero deep disk I/O is performed.
    """
    root = Path(root_dir)
    if not root.exists():
        return []
        
    cache = load_library_cache()
    results = []
    has_changes = False
    current_names = set()

    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir() and not entry.name.startswith('.'):
            name = entry.name
            current_names.add(name)
            sig = get_dir_signature(entry)

            if not force and name in cache and cache[name].get("sig") == sig:
                results.append(cache[name]["data"])
            else:
                data = scan_author_directory(entry)
                cache[name] = {"sig": sig, "data": data}
                results.append(data)
                has_changes = True

    # Evict deleted directories from cache
    for stale in list(cache.keys()):
        if stale not in current_names:
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

