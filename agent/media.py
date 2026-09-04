import re, os, json
import httpx
from loguru import logger
from .config import settings

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

def download(url, path, timeout=60):
    if not url: return None
    try:
        r = httpx.get(url, timeout=timeout, headers=UA, follow_redirects=True)
        if r.status_code == 200 and len(r.content) > 3000:
            open(path, "wb").write(r.content); return path
    except Exception as e:
        logger.warning(f"download failed: {e}")
    return None

def og_image(url):
    if not url or "news.google.com" in url: return None
    try:
        t = httpx.get(url, timeout=15, headers=UA, follow_redirects=True).text
        m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content="([^"]+)"', t)
             or re.search(r'<meta[^>]+content="([^"]+)"[^>]+property=["\']og:image["\']', t))
        img = m.group(1) if m else None
        if not img or not img.startswith("http"): return None
        if any(bad in img.lower() for bad in ("google", "logo", "icon", "sprite", "placeholder")): return None
        return img
    except Exception: return None

def commons_image(query, path):
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", timeout=15, headers=UA, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
            "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1080})
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""): return None
        data = r.json()
        for p in ((data.get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if download(ii.get("thumburl") or ii.get("url"), path): return path
    except Exception: pass
    return None

def openverse_image(query, path):
    try:
        r = httpx.get("https://api.openverse.org/v1/images/", timeout=15, headers=UA, params={"q": query, "page_size": 3})
        if r.status_code != 200: return None
        for item in r.json().get("results", []):
            url = item.get("url") or item.get("thumbnail")
            if url and download(url, path): return path
    except Exception: pass
    return None

def article_video(url):
    """Extracts a direct MP4 URL from a news article (og:video or JSON-LD)."""
    if not url: return None
    try:
        text = httpx.get(url, timeout=15, headers=UA, follow_redirects=True).text
        m = re.search(r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content="([^"]+)"', text)
        if not m: m = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property=["\']og:video', text)
        if m and m.group(1).startswith("http") and ".mp4" in m.group(1): return m.group(1)
        for script in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', text, re.DOTALL):
            try:
                data = json.loads(script)
                if isinstance(data, list): data = data[0]
                if isinstance(data, dict) and data.get("@type") == "VideoObject" and data.get("contentUrl"):
                    return data["contentUrl"]
            except Exception: continue
    except Exception: pass
    return None

def pexels_video(query, path):
    key = getattr(settings, "pexels_key", "")
    if not key or not query: return None
    try:
        r = httpx.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                      params={"query": query, "per_page": 3, "orientation": "portrait"}, timeout=15)
        if r.status_code != 200: return None
        for v in r.json().get("videos", []):
            files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            for f in files:
                if f.get("link") and download(f["link"], path): return path
    except Exception: pass
    return None