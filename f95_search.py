import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from config import get_request_cookies

def search_f95_threads(query: str, limit: int = 5) -> List[Dict[str, str]]:
    cookies = get_request_cookies()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    # XenForo search endpoint
    search_url = f"https://f95zone.to/search/3811804/?q={requests.utils.quote(query)}&o=relevance"
    
    try:
        r = requests.get(search_url, headers=headers, cookies=cookies, timeout=15)
        if r.status_code != 200:
            return []
            
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for h3 in soup.find_all('h3', class_='contentRow-title'):
            a = h3.find('a')
            if not a:
                continue
            href = a.get('href', '')
            if not href.startswith('http'):
                href = 'https://f95zone.to' + href
            
            title = a.get_text(strip=True)
            # Find snippet
            snippet_el = h3.find_next_sibling('div', class_='contentRow-snippet')
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            
            results.append({
                "title": title,
                "url": href,
                "snippet": snippet[:100]
            })
            if len(results) >= limit:
                break
                
        return results
    except Exception as e:
        return []

if __name__ == "__main__":
    import json
    for author in ["Axsens", "Maplestar", "Redmoa"]:
        res = search_f95_threads(author)
        print(f"=== Search results for: {author} (count: {len(res)}) ===")
        for item in res:
            print(f"[{item['title']}] -> {item['url']}")
        print()
