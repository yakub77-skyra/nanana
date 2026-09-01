import re, os
import httpx, trafilatura
from pathlib import Path
from loguru import logger
from .config import settings
from . import media

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
RAW = Path(settings.output_dir).resolve() / "raw"

_html_cache = {}
def get_html(url):
    if url not in _html_cache:
        try:
            _html_cache[url] = httpx.get(url, timeout=20, headers=UA, follow_redirects=True).text
        except Exception as e:
            logger.warning(f"page fetch failed: {e}")
            _html_cache[url] = ""
    return _html_cache[url]

def deep_scrape(url):
    """REAL body text, real quotes, real date from the article."""
    raw = get_html(url)
    if not raw: return {"body": "", "quotes": [], "date": "", "author": ""}
    try:
        text = trafilatura.extract(raw, include_comments=False, favor_recall=True) or ""
        meta = trafilatura.extract_metadata(raw)
        quotes = re.findall(r'["“]([^"”\n]{20,220})["”]', text)
        return {"body": text, "quotes": quotes[:5],
                "date": getattr(meta, "date", "") or "", "author": getattr(meta, "author", "") or ""}
    except Exception as e:
        logger.warning(f"deep_scrape failed: {e}")
        return {"body": "", "quotes": [], "date": "", "author": ""}

def embedded_videos(url):
    """The REAL clips the news site embedded (video tags + YouTube/Twitter embeds)."""
    raw = get_html(url)
    if not raw: return []
    urls = re.findall(r'<(?:video|source)[^>]+src=["\']([^"\']+\.mp4[^"\']*)', raw, re.I)
    urls += [f"https://www.youtube.com/watch?v={m}" for m in
             re.findall(r'(?:youtube\.com/embed|youtu\.be/)([A-Za-z0-9_-]{6,})', raw)]
    urls += re.findall(r'twitter\.com/[^"\s]+/status/\d+', raw)
    return list(dict.fromkeys(urls))[:3]

def clip_from_urls(urls, path, dur=8):
    """Download 5-8s of a real embedded clip."""
    if not urls: return None
    try:
        import yt_dlp
        for u in urls:
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "format": "best[ext=mp4]/best", "outtmpl": path,
                                       "download_ranges": lambda i, y: [{"start_time": 3, "end_time": 3 + dur}]}) as y:
                    y.download([u])
                if os.path.exists(path) and os.path.getsize(path) > 20000:
                    return path
            except Exception as e:
                logger.warning(f"embed clip failed ({e})")
    except Exception:
        pass
    return None

def page_screenshot(url, path):
    """REAL screenshot of the actual article page."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 1080, "height": 1350})
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2500)
            try:
                pg.locator("article, main, h1").first.screenshot(path=path, timeout=5000)
            except Exception:
                pg.screenshot(path=path)
            b.close()
        return path if os.path.exists(path) else None
    except Exception as e:
        logger.warning(f"page screenshot failed: {e}")
        return None

def geocode(location):
    """lat, lon, AND the pin's real country."""
    if not location: return None, None, ""
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search",
                      params={"q": location, "format": "json", "limit": 1},
                      headers={"User-Agent": "NewsReelAgent/1.0"}, timeout=10).json()
        if r:
            return float(r[0]["lat"]), float(r[0]["lon"]), (r[0].get("address") or {}).get("country", "")
    except Exception as e:
        logger.warning(f"geocode failed: {e}")
    return None, None, ""

# ---------------- P6.3 HUMAN EDITOR TOOLKIT ----------------
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
HIDE_JUNK_CSS = """aside,iframe,nav,footer,[class*="advert"],[id*="advert"],[class*="advertisement"],
[class*="sidebar"],[class*="cookie"],[id*="cookie"],[class*="newsletter"],[class*="promo"],
[class*="subscribe"],[class*="share"]{display:none!important}
#handle{top:auto!important;bottom:70px!important}"""

KARAOKE_CSS = (".w{position:relative;display:inline-block;margin-right:.25ch}"
               ".w i{position:absolute;left:-2px;right:-.35ch;top:6%;height:88%;background:#d40000;opacity:.92;"
               "transform:scaleX(0);transform-origin:left;animation:hl .16s forwards}"
               ".w b{position:relative}@keyframes hl{to{transform:scaleX(1)}}")

def mobile_record(url, name, dur, delays=None, scroll=False):
    """Like a human on their phone: mobile layout, ads hidden, native 9:16 recording."""
    from playwright.sync_api import sync_playwright
    RAW.mkdir(parents=True, exist_ok=True)
    css = "*:not(i){animation:none!important;transition:none!important}" + HIDE_JUNK_CSS + (KARAOKE_CSS if delays is not None else "")
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 540, "height": 960},
                                device_scale_factor=1,
                                user_agent=MOBILE_UA, is_mobile=True, has_touch=True,
                                record_video_dir=str(RAW))
            pg = ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2500)
            pg.add_style_tag(content=css)
            pg.wait_for_timeout(3000)
            txt_len = pg.evaluate("() => ((document.body && document.body.innerText) || '').length")
            if txt_len < 200:                      # blank/blocked page → fallback
                pg.close(); ctx.close(); b.close()
                return None
            if delays is not None:
                pg.evaluate(r"""(delays) => {
                    const h = document.querySelector('h1') || document.querySelector('[class*=headline]');
                    if (!h) return;
                    const words = h.textContent.trim().split(/\s+/);
                    h.innerHTML = words.map((w,i)=>`<span class="w"><i style="animation-delay:${(delays[i]||i*0.35).toFixed(2)}s"></i><b>${w.replace(/[&<>]/g,'')}</b></span>`).join(' ');
                }""", delays)
            pg.evaluate("() => { const h=document.querySelector('h1'); if(h) h.scrollIntoView({block:'start'}); }")
            pg.wait_for_timeout(400)
            if scroll:                             # human "browsing" b-roll
                for _ in range(int(dur * 2)):
                    pg.mouse.wheel(0, 260); pg.wait_for_timeout(500)
            else:
                pg.wait_for_timeout(int(dur * 1000))
            v = pg.video; pg.close(); out = v.path(); ctx.close(); b.close()
        return out
    except Exception as e:
        logger.warning(f"mobile record failed: {e}")
        return None

def main_image_url(url):
    """The biggest real photo in the article — the one a human would save."""
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 420, "height": 900}, user_agent=MOBILE_UA)
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2000)
            src = pg.evaluate("""() => {
                let best=null, area=0;
                document.querySelectorAll('article img, main img, figure img, img').forEach(im => {
                    const r = im.getBoundingClientRect(); const a = r.width*r.height;
                    if (a > area && r.width > 200) { area = a; best = im.currentSrc || im.src; }
                });
                return best; }""")
            b.close()
        return src if src and src.startswith("http") else None
    except Exception:
        return None

def commons_video(query, path):
    """Real CC footage from Wikimedia Commons."""
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", timeout=20, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:video {query}", "gsrnamespace": 6,
            "prop": "imageinfo", "iiprop": "url|mime"}).json()
        for p in ((r.get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if "video" in (ii.get("mime") or "") and media.download(ii.get("url"), path, 240):
                return path
    except Exception as e:
        logger.warning(f"commons video failed: {e}")
    return None