import requests
import json
import re
from bs4 import BeautifulSoup
from typing import Dict, List, Any, Optional

from config import get_request_cookies

def analyze_thread(url: str) -> Dict[str, Any]:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    cookies = get_request_cookies()
    resp = requests.get(url, headers=headers, cookies=cookies, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'html.parser')
    
    title_el = soup.find('h1', class_='p-title-value')
    page_title = title_el.get_text(strip=True) if title_el else (soup.title.string if soup.title else "")
    
    # First post / message body
    body = soup.select_one('.message-body .bbWrapper')
    if not body:
        return {"error": "Message body not found", "title": page_title}

    # Extract password if present
    # Look for "Password:" or "pass:" or similar in text
    full_text = body.get_text(separator="\n")
    password = ""
    pwd_match = re.search(r'(?:password|pass|archive password|pwd)[:\s*]+([^\n\r<]+)', full_text, re.IGNORECASE)
    if pwd_match:
        cand = pwd_match.group(1).strip()
        # Clean markdown / emojis
        cand = re.sub(r'[*`_]', '', cand).strip()
        password = cand

    # Extract all links and their surrounding context
    # Usually F95 threads organize downloads under Spoilers or Headers like:
    # "2021-03 Updates" -> [Pixeldrain] [Mega] [GoFile]
    links = []
    for a in body.find_all('a'):
        href = a.get('href')
        if not href:
            continue
        link_text = a.get_text(strip=True)
        # Skip internal F95 navigation / quote links
        if 'f95zone.to/threads/' in href or 'f95zone.to/members/' in href:
            continue
        
        # Parent line / block text context
        parent_text = a.parent.get_text(strip=True) if a.parent else ""
        links.append({
            "text": link_text,
            "url": href,
            "context": parent_text[:120]
        })

    return {
        "title": page_title,
        "password": password,
        "links_count": len(links),
        "links_sample": links[:20]
    }

if __name__ == "__main__":
    test_url = "https://f95zone.to/threads/kidmo-collection-2021-03-28-kidmo.48236/"
    data = analyze_thread(test_url)
    with open("kidmo_sample.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Done! Saved to kidmo_sample.json. Total links:", data.get("links_count"))
    print("Detected Password:", data.get("password"))
