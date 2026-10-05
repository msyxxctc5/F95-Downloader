import re
import time
import logging
import requests
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup, NavigableString, Tag
from urllib.parse import urlparse
from typing import Dict, List, Any, Optional, Set, Tuple
from pathlib import Path

from config import get_request_cookies, load_config, safe_join, safe_filename, get_library_root, get_user_agent
from scanner import scan_author_directory, scan_author_directory_cached, normalize_month

logger = logging.getLogger("akinasync.diff")

def unmask_f95_link_detailed(masked_url: str, cookies: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolves F95zone masked link to the real cloud drive URL with granular error diagnostics.
    Returns: (real_url, error_message)
    """
    if not masked_url.startswith("https://f95zone.to/masked/"):
        return masked_url, None

    # Check if xf_user cookie is provided
    if not cookies or not cookies.get("xf_user"):
        logger.warning("Unmask requested without xf_user cookie for %s", masked_url)
        return None, "未配置 F95zone Cookie (xf_user)，请在设置中粘贴您的 Cookie"

    headers = {
        'User-Agent': get_user_agent(),
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': masked_url
    }
    try:
        resp = requests.post(masked_url, data={'xhr': 1, 'download': 1}, headers=headers, cookies=cookies, timeout=15)
        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("status") == "ok":
                    return data.get("msg"), None
                else:
                    msg = data.get("msg", "未知接口返回")
                    logger.warning("F95zone unmask rejected: %s", msg)
                    return None, f"论坛解密接口拒绝: {msg}"
            except Exception as json_err:
                logger.warning("F95zone unmask returned non-JSON body: %s", json_err)
                return None, "论坛返回非 JSON 响应，可能遭遇防护验证"
        elif resp.status_code == 403:
            logger.warning("F95zone unmask 403 Forbidden for %s", masked_url)
            return None, "论坛访问被拒绝 (403): Cookie 可能已过期或触发 Cloudflare 验证"
        elif resp.status_code == 429:
            logger.warning("F95zone unmask 429 Rate Limited for %s", masked_url)
            return None, "触发论坛防刷限制 (429 Too Many Requests)，请稍后重试"
        else:
            logger.warning("F95zone unmask HTTP %d for %s", resp.status_code, masked_url)
            return None, f"论坛返回异常状态码: HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        logger.warning("F95zone unmask timeout for %s", masked_url)
        return None, "请求论坛解密链接超时 (Timeout)，请检查网络或代理"
    except requests.exceptions.ConnectionError as ce:
        logger.warning("F95zone unmask connection error for %s: %s", masked_url, ce)
        return None, "无法连接到 F95zone 论坛，请检查网络或代理设置"
    except Exception as e:
        logger.error("F95zone unmask unexpected error for %s: %s", masked_url, e)
        return None, f"解析链接发生异常: {str(e)}"

def unmask_f95_link(masked_url: str, cookies: dict) -> Optional[str]:
    """
    Backwards-compatible wrapper returning only the resolved URL.
    """
    url, _ = unmask_f95_link_detailed(masked_url, cookies)
    return url

DOWNLOAD_HOST_DOMAINS = {
    'pixeldrain.com', 'mega.nz', 'mega.io', 'gofile.io', 'workupload.com',
    'buzzheavier.com', 'bzzhr.co', 'datanodes.to', 'uploadhaven.com',
    'vikingfile.com', 'bunkr.is', 'bunkr.ru', 'bunkr.si', 'bunkr.la', 'bunkr.ws', 'bunkr.black',
    'mediafire.com', 'files.fm', 'mixdrop.co', 'mixdrop.to', 'isekaiexpress.com',
    'terminal.lc', 'bowfile.com', 'rapidgator.net', 'katfile.com', 'nitroflare.com',
    'ddownload.com', '1fichier.com', 'krakenfiles.com'
}

KNOWN_HOST_KEYWORDS = (
    'pixeldrain', 'workupload', 'gofile', 'buzzheavier', 'bzzhr',
    'mediafire', 'mega.nz', 'mega.io', 'krakenfiles', 'bunkr'
)

def is_download_link(a_tag: Tag) -> bool:
    href = a_tag.get('href', '').strip()
    if not href or not href.startswith(('http://', 'https://')):
        return False
    try:
        parsed = urlparse(href.lower())
        hostname = (parsed.hostname or '').strip()
        path = parsed.path or ''
    except Exception:
        return False

    # Check F95zone masked link
    if (hostname == 'f95zone.to' or hostname.endswith('.f95zone.to')) and path.startswith('/masked/'):
        return True

    # Exclude internal f95zone pages (threads, members, attachments, tags)
    if 'f95zone.to' in hostname:
        return False

    # Exact or subdomain match for known file hosting domains
    for dom in DOWNLOAD_HOST_DOMAINS:
        if hostname == dom or hostname.endswith('.' + dom):
            return True

    # Secondary check on hostname keywords (avoids path/query substring false positives)
    if any(kw in hostname for kw in KNOWN_HOST_KEYWORDS):
        return True

    return False

def get_mirror_name(a_tag: Tag) -> str:
    text = a_tag.get_text(strip=True).upper()
    if text and text not in ('LINK', 'DOWNLOAD', 'HERE', 'MIRROR'):
        return text
    href = a_tag.get('href', '').lower()
    for host in ('pixeldrain', 'mega.nz', 'mega.io', 'gofile', 'workupload', 'buzzheavier', 'bzzhr',
                 'datanodes', 'uploadhaven', 'vikingfile', 'bunkr', 'mediafire', 'files.fm', 
                 'mixdrop', 'isekaiexpress', 'terminal', 'bowfile', 'rapidgator', 'katfile', 'krakenfiles'):
        if host in href:
            return host.upper()
    return text or "LINK"

LABEL_FALSE_POSITIVES = {
    'download', 'downloads', 'overview', 'genre', 'password', 'changelog', 
    'installation', 'resolution', 'content', 'artist', 'compressed', 'note',
    'notes', 'notice', 'link', 'links', 'mirror', 'mirrors', 'mega', 'pixeldrain', 'gofile',
    'thread', 'status', 'version', 'engine', 'os', 'language', 'developer',
    'bonus', 'bonuses', 'extra', 'extras', 'patreon', 'fanbox', 'fantia',
    'update', 'updates', 'info', 'information', 'preview', 'previews',
    'sample', 'samples', 'screenshots', 'alternative', 'alternatives',
    'file', 'files', 'support', 'credit', 'credits', 'instructions'
}

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
    term_match = re.search(r'\b(Term\s*\d+|Pack\s*\d+|Vol(?:ume)?\.?\s*\d+|Update\s*#?\d+)\b', cleaned, re.I)
    if term_match:
        return term_match.group(1).title()

    # 3. Check work title ending with colon or similar, e.g. "Kaiju No. 8:"
    work_match = re.search(r'^([A-Za-z0-9\s&_\-.#\(\)\'\"]{2,50}):\s*$', cleaned)
    if work_match:
        cand = work_match.group(1).strip()
        # Filter out common false positives with heuristic blacklist
        if cand.lower() not in LABEL_FALSE_POSITIVES:
            return cand

    return None

def extract_password_from_text(full_text: str) -> str:
    """
    Extracts archive password from thread text with strict word boundaries and false-positive filtering.
    """
    pattern = re.compile(
        r'\b(?:archive\s+password|rar\s+password|zip\s+password|7z\s+password|password|pass|pwd)\b\s*[:=\-]\s*([^\n\r<]+)',
        re.IGNORECASE
    )
    
    candidates = []
    for m in pattern.finditer(full_text):
        raw = m.group(1).strip()
        # Remove trailing explanations like "(no quotes)", "(case sensitive)", "(click to view)"
        cleaned = re.sub(r'\s*\(.*?\)\s*$', '', raw).strip()
        # Remove markdown markers and strip surrounding quotes/brackets
        cleaned = re.sub(r'[*`~]', '', cleaned).strip()
        cleaned = cleaned.strip('\'"[]_ ')
        if cleaned.endswith('.') and not cleaned.startswith('.'):
            cleaned = cleaned[:-1].strip()
        
        # Filter out "no password" indicators
        if cleaned.lower() in ('none', 'no', 'n/a', 'na', 'nil', 'null', 'no password', 'none needed', '-'):
            continue
            
        if cleaned:
            candidates.append(cleaned)
            
    if candidates:
        return candidates[0]
    return ""

def parse_f95_thread_universal(url: str) -> Dict[str, Any]:
    cookies = get_request_cookies()
    headers = {
        'User-Agent': get_user_agent(),
        'Accept-Language': 'en-US,en;q=0.9',
    }
    
    try:
        resp = requests.get(url, headers=headers, cookies=cookies, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning("Timeout while fetching thread %s", url)
        return {"error": "请求 F95zone 专楼超时 (Timeout)，请检查网络连接或代理", "title": ""}
    except requests.exceptions.ConnectionError as ce:
        logger.warning("Connection error fetching thread %s: %s", url, ce)
        return {"error": "连接 F95zone 论坛失败，请检查网络或代理设置", "title": ""}
    except requests.exceptions.HTTPError as he:
        status = he.response.status_code if he.response is not None else 0
        logger.warning("HTTP error %d fetching thread %s", status, url)
        if status == 403:
            return {"error": "F95zone 拒绝访问 (403): Cookie 已过期或触发 Cloudflare 验证，请在设置中更新 Cookie", "title": ""}
        elif status == 429:
            return {"error": "论坛请求频率过高 (429 Too Many Requests)，请稍后再刷新", "title": ""}
        return {"error": f"请求专楼失败: HTTP {status}", "title": ""}
    except Exception as e:
        logger.error("Unexpected error fetching thread %s: %s", url, e)
        return {"error": f"抓取专楼发生未知错误: {str(e)}", "title": ""}

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # Thread Title
    title_el = soup.find('h1', class_='p-title-value')
    page_title = title_el.get_text(strip=True) if title_el else (soup.title.string if soup.title else "")

    body = soup.select_one('.message-body .bbWrapper')
    if not body:
        return {"error": "无法获取帖子正文内容。可能原因：F95zone Cookie 已失效需要重新登录，或 IP 触发了 Cloudflare 拦截验证", "title": page_title}

    # Extract Password with refined parser
    full_text = body.get_text(separator="\n")
    password = extract_password_from_text(full_text)

    # Universal traversal with mirror URL deduplication
    current_label = "General"
    items_by_label: Dict[str, List[Dict[str, str]]] = {}
    seen_urls_per_label: Dict[str, Set[str]] = {}
    
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
                href = el.get('href', '').strip()
                if not href:
                    continue
                # If current_label is still general, check previous text sibling
                if current_label == "General":
                    prev = el.find_previous(text=True)
                    if prev:
                        plbl = extract_universal_label(str(prev))
                        if plbl:
                            current_label = plbl
                
                # Deduplicate by URL under the same label
                label_seen = seen_urls_per_label.setdefault(current_label, set())
                if href not in label_seen:
                    label_seen.add(href)
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

_f95_thread_cache: Dict[str, Any] = {}

def get_f95_data_cached(url: str, force: bool = False, ttl_seconds: int = 600) -> Dict[str, Any]:
    global _f95_thread_cache
    now = time.time()
    if not force and url in _f95_thread_cache:
        cached = _f95_thread_cache[url]
        if now - cached["timestamp"] < ttl_seconds:
            return cached["data"]
            
    fresh = parse_f95_thread_universal(url)
    if "error" in fresh:
        # DO NOT cache failed results! Raise so caller knows scraping failed.
        raise RuntimeError(fresh["error"])

    _f95_thread_cache[url] = {
        "timestamp": now,
        "data": fresh
    }
    return fresh

def get_title_numbers(text: str) -> Set[int]:
    base = re.sub(r'\.[a-zA-Z0-9]{2,5}$', '', text.lower())
    base = re.sub(r'\b(1080p|720p|2160p|4k|30fps|60fps)\b', '', base)
    return {int(n) for n in re.findall(r'\d+', base)}

GENERIC_TITLE_TOKENS = {
    'the', 'and', 'for', 'with', 'part', 'vol', 'volume', 'update', 'pack',
    'set', 'bonus', 'extra', 'extras', 'patreon', 'fanbox', 'fantia', 'art',
    'pic', 'pics', 'image', 'images', 'photo', 'photos', 'hd', 'all', 'new',
    'collection', 'release', 'general'
}

def check_local_existence(label: str, local_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Checks if a release label exists in local author directory with high confidence:
    - Month match: returns (True, "2021-03")
    - Term match: returns (True, "Term 154")
    - Standalone work title match with strict token and number verification
    Returns: (is_matched, matched_item_name_or_relpath)
    """
    if not label or label.strip().lower() in ("general", "unknown / general", "unknown", ""):
        return False, None

    norm_lbl = label.lower().strip()
    
    # 1. Month match
    if label in local_data.get("months", []):
        return True, label
    norm_m = normalize_month(label)
    if norm_m and norm_m in local_data.get("months", []):
        return True, norm_m

    # 1b. Year match
    if label in local_data.get("years", []):
        return True, label

    # 2. Term match
    if label in local_data.get("terms", []):
        return True, label
    term_search = re.search(r'\b(term\s*\d+|pack\s*\d+|vol(?:ume)?\.?\s*\d+)\b', norm_lbl, re.I)
    if term_search:
        term_val = term_search.group(1).title()
        if term_val in local_data.get("terms", []):
            return True, term_val
        
    clean_keyword = re.sub(r'[^a-z0-9]', '', norm_lbl)
    if not clean_keyword or clean_keyword in GENERIC_TITLE_TOKENS or len(clean_keyword) < 3:
        return False, None

    # Extract core words excluding generic tokens
    core_words = [w for w in re.split(r'[^a-z0-9]+', norm_lbl) if len(w) >= 3 and w not in GENERIC_TITLE_TOKENS]
    lbl_numbers = get_title_numbers(norm_lbl)

    # If label has neither distinct core words nor numbers, avoid guessing
    if not core_words and not lbl_numbers:
        return False, None

    media_assets = local_data.get("media_assets", [])
    candidates = media_assets if media_assets else [{"name": n, "rel_path": n} for n in local_data.get("all_names", [])]

    for asset in candidates:
        name_lower = asset["name"].lower()
        clean_name = re.sub(r'[^a-z0-9]', '', name_lower)

        # 1. Strict numeric constraint: if label specifies numbers, asset MUST have them
        if lbl_numbers:
            asset_numbers = get_title_numbers(name_lower)
            if not lbl_numbers.issubset(asset_numbers):
                continue

        # 2. Exact match of clean keyword (high confidence)
        if len(clean_keyword) >= 5 and clean_keyword in clean_name:
            return True, asset.get("rel_path") or asset["name"]

        # 3. Multi-word match: require all core words (>= 2 words) to be present
        if len(core_words) >= 2:
            if all(re.search(rf'\b{re.escape(w)}\b', name_lower) or w in clean_name for w in core_words):
                return True, asset.get("rel_path") or asset["name"]
        elif len(core_words) == 1:
            # Single core word: require word-boundary match and sufficient length
            single_word = core_words[0]
            if len(single_word) >= 4 and re.search(rf'\b{re.escape(single_word)}\b', name_lower):
                return True, asset.get("rel_path") or asset["name"]

    return False, None

def compare_local_vs_f95(author_name: str, thread_url: str, force: bool = False) -> Dict[str, Any]:
    lib_root = get_library_root()
    clean_author = safe_filename(author_name)
    author_path = safe_join(lib_root, clean_author)

    local_data = scan_author_directory_cached(author_path, force=force)
    f95_data = get_f95_data_cached(thread_url, force=force)
    releases_dict = f95_data.get("releases", {})

    diff_list = []
    all_labels = list(releases_dict.keys())
    
    for lbl in all_labels:
        mirrors = releases_dict[lbl]
        exists, matched_asset = check_local_existence(lbl, local_data)
        diff_list.append({
            "month": lbl, # release label
            "exists_locally": exists,
            "matched_asset": matched_asset,
            "status": "DOWNLOADED" if exists else "MISSING",
            "mirrors_count": len(mirrors),
            "mirrors": mirrors
        })

    downloaded_labels = [
        item["month"] for item in diff_list 
        if item["exists_locally"] and item["month"] not in ("Unknown / General", "General")
    ]

    missing_labels = [
        item["month"] for item in diff_list 
        if not item["exists_locally"] and item["month"] not in ("Unknown / General", "General")
    ]
    
    valid_f95_labels = [lbl for lbl in all_labels if lbl not in ("Unknown / General", "General")]
    
    return {
        "author": author_name,
        "thread_title": f95_data.get("title"),
        "password": f95_data.get("password") or "f95zone",
        "local_months_count": len(downloaded_labels),
        "local_months": local_data.get("months", []),
        "local_years": local_data.get("years", []),
        "f95_months_count": len(valid_f95_labels),
        "missing_count": len(missing_labels),
        "missing_months": missing_labels,
        "releases": diff_list
    }

if __name__ == "__main__":
    print("AkinaSync Universal Diff Engine. Run via test suite or server API.")
