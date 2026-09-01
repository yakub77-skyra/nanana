import re, os
import httpx, trafilatura
from pathlib import Path
from loguru import logger
from .config import settings
from . import media

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
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

def get_text_jina(url):
    """Anti-ban reader-proxy: server-side fetch, returns clean article text."""
    try:
        r = httpx.get(f"https://r.jina.ai/{url}", timeout=40,
                      headers={"User-Agent": "NewsReelAgent/1.0"})
        if r.status_code == 200 and len(r.text) > 300:
            return r.text
    except Exception as e:
        logger.warning(f"jina reader failed: {e}")
    return ""

def _valid_quote(q):
    q = (q or "").strip()
    if len(q) < 30 or len(q) > 220: return False
    low = q.lower()
    if any(b in low for b in ("http", "www.", "cid/", ".com", ".in/")): return False
    if len(q.split()) < 6: return False
    if sum(c.isalpha() for c in q) / max(len(q), 1) < 0.6: return False
    return True

def deep_scrape(url):
    raw = get_html(url)
    text = ""
    if raw:
        try:
            text = trafilatura.extract(raw, include_comments=False, favor_recall=True) or ""
        except Exception:
            text = ""
    if len(text) < 300:                      # blocked site → reader-proxy
        text = get_text_jina(url)
    if not raw and not text:
        return {"body": "", "quotes": [], "date": "", "author": ""}
    try:
        meta = trafilatura.extract_metadata(raw) if raw else None
    except Exception:
        meta = None
    quotes = [q.strip() for q in re.findall(r'["“]([^"”\n]{20,220})["”]', text) if _valid_quote(q.strip())]
    return {"body": text, "quotes": quotes[:3],
            "date": (getattr(meta, "date", "") if meta else "") or "",
            "author": (getattr(meta, "author", "") if meta else "") or ""}

def match_article(target, articles):
    """M019 strict token matcher — no substring false hits."""
    toks = [w for w in re.split(r"[^a-zA-Z0-9]+", (target or "").lower()) if len(w) >= 4]
    if not toks: return None
    for a in articles:
        tt = set(re.split(r"[^a-zA-Z0-9]+", a["title"].lower()))
        if sum(t in tt for t in toks[:6]) >= 2:
            return a
    return None

def embedded_videos(url):
    raw = get_html(url)
    if not raw: return []
    urls = re.findall(r'<(?:video|source)[^>]+src=["\']([^"\']+\.mp4[^"\']*)', raw, re.I)
    urls += [f"https://www.youtube.com/watch?v={m}" for m in
             re.findall(r'(?:youtube\.com/embed|youtu\.be/)([A-Za-z0-9_-]{6,})', raw)]
    return list(dict.fromkeys(urls))[:4]

def clip_from_urls(urls, path, dur=8):
    if not urls: return None
    try:
        import yt_dlp
        for u in urls:
            try:
                opts = {"quiet": True, "format": "best[ext=mp4]/best", "outtmpl": path,
                        "download_ranges": lambda i, y: [{"start_time": 3, "end_time": 3 + dur}]}
                try:
                    with yt_dlp.YoutubeDL(opts) as y: y.download([u])
                except Exception:
                    opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
                    with yt_dlp.YoutubeDL(opts) as y: y.download([u])
                if os.path.exists(path) and os.path.getsize(path) > 20000:
                    return path
            except Exception as e:
                logger.warning(f"embed clip failed ({e})")
    except Exception:
        pass
    return None

_BAD_PAGE_RE = r"access denied|don't have permission|captcha|verify you are human|are you a robot|blocked|incident id|request unsuccessful|cloudflare|attention required"

def _is_blocked_page(pg):
    try:
        return pg.evaluate(f"""() => {{
            const t = ((document.body && document.body.innerText) || '').toLowerCase();
            return /{_BAD_PAGE_RE}/.test(t);
        }}""")
    except Exception:
        return False

def page_screenshot(url, path):
    """Real article-page screenshot (the floating card look). Anti-bot guarded."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page(viewport={"width": 900, "height": 1200})
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2500)
            if _is_blocked_page(pg):
                b.close(); return None
            try:
                pg.locator("article, main, h1").first.screenshot(path=path, timeout=6000)
            except Exception:
                pg.screenshot(path=path)
            b.close()
        return path if os.path.exists(path) else None
    except Exception as e:
        logger.warning(f"page screenshot failed: {e}")
        return None

def geocode(location):
    if not location: return None, None, ""
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/search",
                      params={"q": location, "format": "json", "limit": 1, "addressdetails": 1},
                      headers={"User-Agent": "NewsReelAgent/1.0"}, timeout=10).json()
        if r:
            return float(r[0]["lat"]), float(r[0]["lon"]), (r[0].get("address") or {}).get("country", "")
    except Exception as e:
        logger.warning(f"geocode failed: {e}")
    return None, None, ""

HIDE_JUNK_CSS = """aside,iframe,nav,footer,[class*="advert"],[id*="advert"],[class*="advertisement"],
[class*="sidebar"],[class*="cookie"],[id*="cookie"],[class*="newsletter"],[class*="promo"],
[class*="subscribe"],[class*="share"],[class*="ad-slot"],[id*="ad-slot"],[class*="ads"],[id*="ads"],
[id*="gpt"],[class*="gpt"],[class*="-ad-"],[id*="-ad-"],[class*="ad_"],[id*="ad_"],
[class*="outbrain"],[id*="outbrain"],[class*="taboola"],[id*="taboola"],
[class*="recommended"],[class*="related"],[class*="paywall"]{display:none!important}
body{overflow-x:hidden!important}"""

KARAOKE_CSS = (".w{position:relative;display:inline-block;margin-right:.25ch}"
               ".w i{position:absolute;left:-2px;right:-.35ch;top:6%;height:88%;background:#d40000;opacity:.92;"
               "transform:scaleX(0);transform-origin:left;animation:hl .16s forwards}"
               ".w b{position:relative}@keyframes hl{to{transform:scaleX(1)}}")

def mobile_record(url, name, dur, delays=None, scroll=False):
    from playwright.sync_api import sync_playwright
    RAW.mkdir(parents=True, exist_ok=True)
    css = "*:not(i){animation:none!important;transition:none!important}" + HIDE_JUNK_CSS + (KARAOKE_CSS if delays is not None else "")
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(viewport={"width": 540, "height": 960}, device_scale_factor=1,
                                user_agent=MOBILE_UA, is_mobile=True, has_touch=True,
                                record_video_dir=str(RAW))          # native 9:16 (M010)
            pg = ctx.new_page()
            pg.goto(url, wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2500)
            pg.add_style_tag(content=css)
            pg.wait_for_timeout(1500)
            txt_len = pg.evaluate("() => ((document.body && document.body.innerText) || '').length")
            if txt_len < 200 or _is_blocked_page(pg):               # M018 anti-bot guard
                pg.close(); ctx.close(); b.close(); return None
            if delays is not None:
                pg.evaluate(r"""(delays) => {
                    const h = document.querySelector('h1') || document.querySelector('[class*=headline]');
                    if (!h) return;
                    const esc = s => s.replace(/[&<>]/g, '');
                    const words = h.textContent.trim().split(/\s+/);
                    h.innerHTML = words.map((w,i)=>`<span class="w"><i style="animation-delay:${(delays[i]||i*0.35).toFixed(2)}s"></i><b>${esc(w)}</b></span>`).join(' ');
                }""", delays)
            pg.evaluate("() => { const h=document.querySelector('h1'); if(h) h.scrollIntoView({block:'start'}); }")
            pg.wait_for_timeout(400)
            if scroll:
                for _ in range(max(1, int(dur * 2))):
                    pg.mouse.wheel(0, 260); pg.wait_for_timeout(500)
            else:
                pg.wait_for_timeout(int(dur * 1000))
            v = pg.video; pg.close(); out = v.path(); ctx.close(); b.close()
        return out
    except Exception as e:
        logger.warning(f"mobile record failed: {e}")
        return None

def main_image_url(url):
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
                    const s = im.currentSrc || im.src || '';
                    if (a > area && r.width > 180 && s.startsWith('http')
                        && !/logo|icon|sprite|avatar/i.test(s)) { area = a; best = s; }
                });
                return best; }""")
            b.close()
        return src if src and src.startswith("http") else None
    except Exception:
        return None

def _commons_search(query, path, kind="bitmap", width=1080, timeout=20):
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", timeout=timeout, params={
            "action": "query", "format": "json", "generator": "search",
            "gsrsearch": f"filetype:{kind} {query}", "gsrnamespace": 6,
            "prop": "imageinfo", "iiprop": "url|mime", "iiurlwidth": width})
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return None
        for p in ((r.json().get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [{}])[0]
            if kind == "video" and "video" not in (ii.get("mime") or ""): continue
            if media.download(ii.get("thumburl") or ii.get("url"), path, 240):
                return path
    except Exception as e:
        logger.warning(f"commons {kind} failed: {e}")
    return None

def commons_image(query, path):  return _commons_search(query, path, "bitmap", 1080)
def commons_video(query, path):  return _commons_search(query, path, "video", 720)
def commons_portrait(name, path): return _commons_search(f"{name} portrait", path, "bitmap", 800)

def commons_texture(path):
    """Cached equirectangular earth texture for the pro terrain map."""
    if os.path.exists(path): return path
    return _commons_search("equirectangular earth satellite", path, "bitmap", 2000, timeout=40)