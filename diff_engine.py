import re
import requests
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup, NavigableString, Tag
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

from config import get_request_cookies, load_config
from scanner import scan_author_directory, normalize_month

def unmask_f95_link(masked_url: str, cookies: dict) -> Optional[str]:
    """
    Resolves F95zone masked link to the real cloud drive URL.
    """
    if not masked_url.startswith("https://f95zone.to/masked/"):
        return masked_url
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': masked_url
    }
    try:
        resp = requests.post(masked_url, data={'xhr': 1, 'download': 1}, headers=headers, cookies=cookies, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok":
                return data.get("msg")
    except Exception:
        pass
    return None

COMMON_FILE_HOSTS = (
    'f95zone.to/masked/', 'pixeldrain', 'mega.nz', 'gofile', 'workupload',
    'bzzhr', 'buzzheavier', 'datanodes', 'uploadhaven', 'vikingfile', 'bunkr',
    'mediafire', 'files.fm', 'mixdrop', 'isekaiexpress', 'terminal.lc', 'bowfile',
    'rapidgator', 'katfile', 'nitroflare', 'ddownload', '1fichier', 'krakenfiles'
)

def is_download_link(a_tag: Tag) -> bool:
    href = a_tag.get('href', '').lower()
    if not href.startswith('http'):
        return False
    if 'attachments.f95zone.to' in href or 'f95zone.to/attachments/' in href:
        return False
    if 'f95zone.to/threads/' in href or 'f95zone.to/members/' in href or 'f95zone.to/tags/' in href:
        return False
    return any(host in href for host in COMMON_FILE_HOSTS)

def get_mirror_name(a_tag: Tag) -> str:
    text = a_tag.get_text(strip=True).upper()
    if text and text not in ('LINK', 'DOWNLOAD', 'HERE', 'MIRROR'):
        return text
    href = a_tag.get('href', '').lower()
    for host in ('pixeldrain', 'mega.nz', 'gofile', 'workupload', 'buzzheavier', 'bzzhr',
                 'datanodes', 'uploadhaven', 'vikingfile', 'bunkr', 'mediafire', 'files.fm', 
                 'mixdrop', 'isekaiexpress', 'terminal', 'bowfile', 'rapidgator', 'katfile'):
        if host in href:
            return host.upper()
    return text or "LINK"

def extract_universal_label(text: str) -> Optional[str]:
    """
    Extracts release identifier from text:
    1. Standard Month (e.g., 2021-03, 04-2019, 2026-09)
    2. Term / Pack / Vol / Volume (e.g., Term 71, Pack 05, Vol.3)
    3. Named Work / Title (e.g., "Kaiju No. 8:", "Sono Bisque Doll:", "Fern x Stark:")
    """
    if not text:
        return None
    cleaned = text.strip()
    
    # 1. Check month first
    m = normalize_month(cleaned)
    if m:
        return m
        
    # 2. Check Term / Pack / Vol / Update
    term_match = re.search(r'(Term\s*\d+|Pack\s*\d+|Vol(?:ume)?\.?\s*\d+|Update\s*#?\d+)', cleaned, re.I)
    if term_match:
        return term_match.group(1).title()

    # 3. Check work title ending with colon or similar, e.g. "Kaiju No. 8:"
    work_match = re.search(r'^([A-Za-z0-9\s&_\-.#\(\)\'\"]{2,50}):\s*$', cleaned)
    if work_match:
        cand = work_match.group(1).strip()
        # Filter out common false positives
        if cand.lower() not in (
            'download', 'downloads', 'overview', 'genre', 'password', 'changelog', 
            'installation', 'resolution', 'content', 'artist', 'compressed', 'note',
            'link', 'links', 'mirror', 'mirrors', 'mega', 'pixeldrain', 'gofile',
            'thread', 'status', 'version', 'engine', 'os', 'language', 'developer'
        ):
            return cand

    return None

def parse_f95_thread_universal(url: str) -> Dict[str, Any]:
    cookies = get_request_cookies()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    resp = requests.get(url, headers=headers, cookies=cookies, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Thread Title
    title_el = soup.find('h1', class_='p-title-value')
    page_title = title_el.get_text(strip=True) if title_el else (soup.title.string if soup.title else "")

    body = soup.select_one('.message-body .bbWrapper')
    if not body:
        return {"error": "Message body not found", "title": page_title}

    # Extract Password
    full_text = body.get_text(separator="\n")
    password = ""
    pwd_match = re.search(r'(?:password|pass|archive password|pwd)[:\s*]+([^\n\r<]+)', full_text, re.IGNORECASE)
    if pwd_match:
        password = re.sub(r'[*`_]', '', pwd_match.group(1)).strip()

    # Universal traversal
    current_label = "General"
    items_by_label: Dict[str, List[Dict[str, str]]] = {}
    
    for el in body.descendants:
        if isinstance(el, NavigableString):
            t = str(el).strip()
            if not t:
                continue
            lbl = extract_universal_label(t)
            if lbl:
                current_label = lbl
        elif isinstance(el, Tag) and el.name == 'a':
            if is_download_link(el):
                mirror_name = get_mirror_name(el)
                href = el.get('href', '')
                # If current_label is still general, check previous text sibling
                if current_label == "General":
                    prev = el.find_previous(text=True)
                    if prev:
                        plbl = extract_universal_label(str(prev))
                        if plbl:
                            current_label = plbl
                            
                items_by_label.setdefault(current_label, []).append({
                    "mirror": mirror_name,
                    "masked_url": href,
                    "url": href
                })
        
    return {
        "title": page_title,
        "password": password or "f95zone",
        "releases": items_by_label
    }

def check_local_existence(label: str, local_data: Dict[str, Any]) -> bool:
    """
    Fuzzy checks if a release label exists in local author directory:
    - By month: e.g. "2021-03" in local_data["months"]
    - By term / name: substring search or keyword matching in all local folder names or files
    """
    norm_lbl = label.lower().strip()
    
    # 1. Exact or normalized month match
    if label in local_data.get("months", []):
        return True
        
    # 2. Check in all local items (files and subfolders)
    path = Path(local_data.get("path", ""))
    if not path.exists():
        return False
        
    clean_keyword = re.sub(r'[^a-z0-9]', '', norm_lbl)
    if not clean_keyword:
        return False

    # Extract significant words (e.g. "kaiju", "sono", "bisque", "doll")
    significant_words = [w for w in re.split(r'[^a-z0-9]+', norm_lbl) if len(w) >= 3 and w not in ('the', 'and', 'part', 'vol')]

    try:
        for entry in path.rglob("*"):
            clean_name = re.sub(r'[^a-z0-9]', '', entry.name.lower())
            # Substring match (e.g. "kaijuno8" in "maplestar_kaijuno8_1080p")
            if clean_keyword in clean_name:
                return True
            # Word set match if significant words exist
            if significant_words and all(w in clean_name for w in significant_words):
                return True
    except Exception:
        pass

    return False

def compare_local_vs_f95(author_name: str, thread_url: str) -> Dict[str, Any]:
    cfg = load_config()
    lib_root = Path(cfg.get("library_root", r"H:\akinaclub"))
    author_path = lib_root / author_name

    local_data = scan_author_directory(author_path)
    f95_data = parse_f95_thread_universal(thread_url)
    releases_dict = f95_data.get("releases", {})

    diff_list = []
    all_labels = list(releases_dict.keys())
    
    for lbl in all_labels:
        mirrors = releases_dict[lbl]
        exists = check_local_existence(lbl, local_data)
        diff_list.append({
            "month": lbl, # release label
            "exists_locally": exists,
            "status": "DOWNLOADED" if exists else "MISSING",
            "mirrors_count": len(mirrors),
            "mirrors": mirrors
        })

    missing_labels = [
        item["month"] for item in diff_list 
        if not item["exists_locally"] and item["month"] not in ("Unknown / General", "General")
    ]
    
    valid_f95_labels = [lbl for lbl in all_labels if lbl not in ("Unknown / General", "General")]
    
    return {
        "author": author_name,
        "thread_title": f95_data.get("title"),
        "password": f95_data.get("password") or "f95zone",
        "local_months_count": local_data.get("month_count", 0),
        "local_months": local_data.get("months", []),
        "f95_months_count": len(valid_f95_labels),
        "missing_count": len(missing_labels),
        "missing_months": missing_labels,
        "releases": diff_list
    }

if __name__ == "__main__":
    # Test on Axsens, Maplestar, and Kidmo
    test_suite = [
        ("Kidmo", "https://f95zone.to/threads/kidmo-collection-2021-03-28-kidmo.48236/"),
        ("Axsens", "https://f95zone.to/threads/axsens-collection-2026-08-31-axsens.32601/"),
        ("Maplestar", "https://f95zone.to/threads/maplestar-collection-2026-09-16-maplestar_art.73407/")
    ]
    for author, url in test_suite:
        res = compare_local_vs_f95(author, url)
        print(f"=== Universal Diff for [{author}] ===")
        print(f"F95 Releases Count: {res['f95_months_count']}")
        print(f"Local Items Count:  {res['local_months_count']}")
        print(f"Missing Count:      {res['missing_count']}")
        print(f"Missing Sample:     {res['missing_months'][:5]}")
        print()
