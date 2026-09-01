import re
import httpx
from loguru import logger

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def download(url, path, timeout=120):
    if not url: return None
    try:
        r = httpx.get(url, timeout=timeout, headers=UA, follow_redirects=True)
        if r.status_code == 200 and len(r.content) > 5000:
            open(path, "wb").write(r.content); return path
    except Exception as e:
        logger.warning(f"download failed: {e}")
    return None

def og_image(url):
    """Real publisher photo — with guards against logos/placeholders."""
    if not url or "news.google.com" in url:
        return None
    try:
        t = httpx.get(url, timeout=15, headers=UA, follow_redirects=True).text
        m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', t)
             or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', t))
        img = m.group(1) if m else None
        if not img or not img.startswith("http"): return None
        if any(bad in img.lower() for bad in ("google", "logo", "icon", "sprite", "placeholder")):
            return None
        return img
    except Exception:
        return None

def commons_image(query, path):
    """Real CC-licensed press-type photos (keyless)."""
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", timeout=20, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
            "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1080}).json()
        for p in ((r.get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if download(ii.get("thumburl") or ii.get("url"), path): return path
    except Exception as e:
        logger.warning(f"commons failed: {e}")
    return None