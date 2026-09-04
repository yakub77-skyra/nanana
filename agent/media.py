import re, os
import httpx
from loguru import logger

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
             or re.search(r'<meta[^>]+content="([^"]+)["\'][^>]+property=["\']og:image["\']', t))
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

def satellite_terrain(path):
    """Downloads a real NASA Blue Marble earth image (highly reliable) or returns None."""
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        return path
    # NASA Visible Earth - very reliable, no bot protection
    nasa_url = "https://eoimages.gsfc.nasa.gov/images/imagerecords/74000/74393/world.topo.bathy.200412.3x5400x2700.jpg"
    if download(nasa_url, path, timeout=30):
        return path
    return None