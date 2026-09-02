
import html as _html, os, base64, datetime, json, math, re, random
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from .config import settings

RAW = Path(settings.output_dir).resolve() / "raw"

# ------------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------------
def _date_str():
    ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b").upper()

def _b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()

def _b64_or_empty(p):
    if p and os.path.exists(p):
        return base64.b64encode(Path(p).read_bytes()).decode()
    return ""

def record_html(page_html, dur, name, viewport=(1080, 1920)):
    """Record HTML page as MP4 video via Playwright."""
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}.html"
    p.write_text(page_html, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            record_video_dir=str(RAW),
            record_video_size={"width": viewport[0], "height": viewport[1]}
        )
        pg = ctx.new_page()
        pg.goto(p.resolve().as_uri())
        pg.wait_for_timeout(int(dur * 1000))
        v = pg.video
        pg.close()
        out = v.path()
        ctx.close()
        b.close()
    return out

# ------------------------------------------------------------------
# GEOJSON for country outlines
# ------------------------------------------------------------------
def _geojson():
    if not hasattr(_geojson, "cache"):
        url = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
        try:
            _geojson.cache = httpx.get(url, timeout=60).json()
        except Exception:
            _geojson.cache = {"features": []}
    return _geojson.cache

def has_country(name):
    if not name:
        return False
    n = name.lower()
    return any(n == (f["properties"].get("NAME") or "").lower()
               or n in (f["properties"].get("NAME") or "").lower()
               for f in _geojson()["features"])

def get_country_path(name):
    """Get SVG path data for a country."""
    gj = _geojson()["features"]
    nm = lambda f: (f["properties"].get("NAME") or "").lower()
    target = next((f for f in gj if nm(f) == name.lower()), None)
    if target is None:
        target = next((f for f in gj if name.lower() in nm(f)), None)
    if target is None:
        return None, None, None
    
    rings = lambda f: ([p[0] for p in f["geometry"]["coordinates"]] if f["geometry"]["type"] == "MultiPolygon"
                       else [f["geometry"]["coordinates"][0]])
    tr = rings(target)
    txs = [c[0] for r in tr for c in r]
    tys = [c[1] for r in tr for c in r]
    cx, cy = (min(txs)+max(txs))/2, (min(tys)+max(tys))/2
    w = max(max(txs)-min(txs), 20)
    
    X = lambda lo: (lo + 180) * 6
    Y = lambda la: (90 - la) * 6
    
    d = "".join("M" + "L".join(f"{X(c[0]):.0f} {Y(c[1]):.0f}" for c in r[::2]) + "Z" for r in rings(target))
    return d, cx, cy

# ------------------------------------------------------------------
# SHARED COMPONENTS
# ------------------------------------------------------------------
LOGO_SVG = """<svg id="logo" width="140" height="50" viewBox="0 0 140 50" style="position:fixed;top:28px;left:28px;z-index:9999">
  <text x="0" y="32" fill="#fff" font-family="Arial Black, Arial, sans-serif" font-size="26" font-weight="900" letter-spacing="1">INDIA</text>
  <text x="78" y="32" fill="#e11" font-family="Arial Black, Arial, sans-serif" font-size="26" font-weight="900">24</text>
  <path d="M 62 8 L 65 12 L 70 10 L 68 15 L 72 18 L 67 19 L 66 24 L 62 20 L 58 24 L 57 19 L 52 18 L 56 15 L 54 10 L 59 12 Z" fill="#e11" opacity="0.9"/>
</svg>"""

HANDLE_HTML = """<div id="handle" style="position:fixed;top:28px;right:28px;z-index:9999;display:flex;align-items:center;gap:8px">
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
    <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/>
    <line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/>
  </svg>
  <span style="color:#fff;font-family:Arial,sans-serif;font-weight:800;font-size:20px;letter-spacing:1px;text-shadow:0 2px 8px rgba(0,0,0,0.8)">@INDIAINLAST24HR</span>
</div>"""

# ------------------------------------------------------------------
# SCENE 1: MAP INTRO (3D satellite map with glowing country)
# ------------------------------------------------------------------
def map_intro_html(country, overlay_text, dur, theme="purple", topic_img=None, pin=None):
    colors = {
        "purple": {"glow": "#c026d3", "glow2": "#7c3aed", "accent": "#e879f9"},
        "red": {"glow": "#dc2626", "glow2": "#991b1b", "accent": "#f87171"},
        "blue": {"glow": "#2563eb", "glow2": "#1e40af", "accent": "#60a5fa"},
    }
    c = colors.get(theme, colors["purple"])
    path_d, cx, cy = get_country_path(country)
    if not path_d:
        path_d, cx, cy = get_country_path("India") or ("", 78.0, 22.0)
    pin_b64 = _b64_or_empty(topic_img)
    pin_html = f"""<div class="pin-wrap">
        <div class="pin-ring"><img src="data:image/jpeg;base64,{pin_b64}"/></div>
        <div class="pin-label">{_html.escape(pin or country)}</div>
    </div>""" if pin_b64 else ""
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0;animation:zoomIn {dur:.2f}s cubic-bezier(0.25,0.1,0.25,1) forwards}}
@keyframes zoomIn{{from{{transform:scale(1)}}to{{transform:scale(1.6)}}}}
#map-bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(0.7) brightness(0.25) contrast(1.3)}}
#vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center, transparent 20%, rgba(0,0,0,0.7) 70%, rgba(0,0,0,0.95) 100%);pointer-events:none}}
#clouds{{position:absolute;inset:0;pointer-events:none;opacity:0.4}}
.cloud{{position:absolute;background:radial-gradient(ellipse, rgba(255,255,255,0.08) 0%, transparent 70%);border-radius:50%}}
.c1{{width:600px;height:300px;top:-50px;left:-100px;animation:drift1 20s infinite}}
.c2{{width:500px;height:250px;top:200px;right:-150px;animation:drift2 25s infinite}}
.c3{{width:700px;height:350px;bottom:-100px;left:200px;animation:drift1 30s infinite}}
.c4{{width:400px;height:200px;top:600px;left:100px;animation:drift2 18s infinite}}
@keyframes drift1{{0%,100%{{transform:translateX(0)}}50%{{transform:translateX(80px)}}}}
@keyframes drift2{{0%,100%{{transform:translateX(0)}}50%{{transform:translateX(-60px)}}}}
#map-svg{{position:absolute;inset:0;width:100%;height:100%}}
.country-path{{fill:url(#countryGrad);stroke:#fff;stroke-width:2;filter:url(#glow);animation:pulseGlow 3s ease-in-out infinite}}
@keyframes pulseGlow{{0%,100%{{filter:url(#glow)}}50%{{filter:url(#glowBright)}}}}
#overlay-text{{position:absolute;top:35%;left:0;width:100%;text-align:center;color:#fff;font-weight:900;font-size:68px;letter-spacing:3px;text-transform:uppercase;text-shadow:0 4px 30px rgba(0,0,0,0.9), 0 0 60px {c["glow"]};padding:0 60px;line-height:1.2;animation:textFade {dur:.2f}s ease-out forwards;opacity:0}}
@keyframes textFade{{0%{{opacity:0;transform:translateY(30px)}}30%{{opacity:0;transform:translateY(30px)}}100%{{opacity:1;transform:translateY(0)}}}}
.pin-wrap{{position:absolute;left:50%;top:52%;transform:translate(-50%,-50%);text-align:center;animation:pinPop 0.6s 0.8s ease-out forwards;opacity:0}}
@keyframes pinPop{{0%{{opacity:0;transform:translate(-50%,-50%) scale(0.5)}}100%{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
.pin-ring{{width:180px;height:180px;border-radius:50%;border:4px solid #fff;overflow:hidden;margin:0 auto;box-shadow:0 0 50px {c["glow"]}, 0 0 80px {c["glow2"]};background:#1a1a1a;animation:pinPulse 2s ease-in-out infinite}}
@keyframes pinPulse{{0%,100%{{box-shadow:0 0 50px {c["glow"]}, 0 0 80px {c["glow2"]}}}50%{{box-shadow:0 0 70px {c["glow"]}, 0 0 120px {c["glow2"]}}}}}
.pin-ring img{{width:100%;height:100%;object-fit:cover}}
.pin-label{{margin-top:14px;background:#fff;color:#111;font-weight:900;font-size:38px;letter-spacing:2px;padding:10px 28px;border-radius:10px;display:inline-block;box-shadow:0 6px 30px rgba(0,0,0,0.8)}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <svg id="map-bg" viewBox="0 0 2160 1080" preserveAspectRatio="xMidYMid slice">
    <defs>
      <pattern id="noise" width="100" height="100" patternUnits="userSpaceOnUse">
        <filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.6" numOctaves="3" stitchTiles="stitch"/></filter>
        <rect width="100" height="100" filter="url(#n)" opacity="0.08"/>
      </pattern>
      <linearGradient id="countryGrad" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="{c["glow"]}"/>
        <stop offset="100%" stop-color="{c["glow2"]}"/>
      </linearGradient>
      <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="6" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="glowBright" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="12" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <rect width="2160" height="1080" fill="#0a0a0a"/>
    <rect width="2160" height="1080" fill="url(#noise)"/>
    <path fill="none" stroke="#222" stroke-width="0.8" d="{path_d or ""}"/>
    <path class="country-path" d="{path_d or ""}"/>
  </svg>
  <div id="vignette"></div>
  <div id="clouds">
    <div class="cloud c1"></div>
    <div class="cloud c2"></div>
    <div class="cloud c3"></div>
    <div class="cloud c4"></div>
  </div>
  <div id="overlay-text">{_html.escape(overlay_text or "INDIA NEWS")}</div>
  {pin_html}
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 2: NEWS FRAME (numbered headline frame on map background)
# ------------------------------------------------------------------
def news_frame_html(number, headline, photo_b64, location, dur, theme="purple"):
    colors = {
        "purple": {"glow": "#c026d3", "numColor": "#e879f9"},
        "red": {"glow": "#dc2626", "numColor": "#f87171"},
        "blue": {"glow": "#2563eb", "numColor": "#60a5fa"},
    }
    c = colors.get(theme, colors["purple"])
    path_d, _, _ = get_country_path("India") or ("", None, None)
    safe_headline = _html.escape(headline or "HEADLINE")
    safe_location = _html.escape(location or "INDIA")
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0}}
#map-bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(0.8) brightness(0.2) contrast(1.2)}}
#vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.6) 100%);pointer-events:none}}
#india-outline{{position:absolute;inset:0;width:100%;height:100%;opacity:0.3}}
#india-outline path{{fill:none;stroke:#fff;stroke-width:1.5;filter:drop-shadow(0 0 8px {c["glow"]})}}
#frame-wrap{{position:absolute;top:80px;left:50%;transform:translateX(-50%);width:920px;animation:frameIn 0.5s ease-out forwards;opacity:0}}
@keyframes frameIn{{0%{{opacity:0;transform:translateX(-50%) translateY(-40px) scale(0.95)}}100%{{opacity:1;transform:translateX(-50%) translateY(0) scale(1)}}}}
#photo-frame{{width:920px;height:520px;border:3px dashed #ffeb3b;border-radius:8px;overflow:hidden;position:relative;box-shadow:0 0 30px rgba(255,235,59,0.15), inset 0 0 30px rgba(0,0,0,0.3)}}
#photo-frame::before{{content:'';position:absolute;inset:0;border:2px solid rgba(255,235,59,0.3);border-radius:6px;pointer-events:none}}
#photo-frame img{{width:100%;height:100%;object-fit:cover}}
#connector{{position:absolute;top:600px;left:50%;transform:translateX(-50%);width:4px;height:120px;background:linear-gradient(to bottom, #ffeb3b, transparent);animation:lineGrow 0.4s 0.3s ease-out forwards;transform-origin:top;transform:translateX(-50%) scaleY(0)}}
@keyframes lineGrow{{0%{{transform:translateX(-50%) scaleY(0)}}100%{{transform:translateX(-50%) scaleY(1)}}}}
#num-circle{{position:absolute;top:700px;left:50%;transform:translateX(-50%);width:100px;height:100px;border-radius:50%;background:linear-gradient(135deg, {c["numColor"]}, {c["glow"]});display:flex;align-items:center;justify-content:center;box-shadow:0 0 40px {c["glow"]}, 0 0 80px rgba(0,0,0,0.5);animation:circlePop 0.5s 0.5s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0;z-index:10}}
@keyframes circlePop{{0%{{opacity:0;transform:translateX(-50%) scale(0)}}100%{{opacity:1;transform:translateX(-50%) scale(1)}}}}
#num-circle span{{color:#fff;font-size:52px;font-weight:900;font-family:Arial Black;text-shadow:0 2px 10px rgba(0,0,0,0.5)}}
#headline-box{{position:absolute;top:840px;left:50%;transform:translateX(-50%);width:900px;background:rgba(0,0,0,0.75);border:1px solid rgba(255,255,255,0.15);border-radius:12px;padding:30px 40px;backdrop-filter:blur(10px);animation:textIn 0.6s 0.7s ease-out forwards;opacity:0}}
@keyframes textIn{{0%{{opacity:0;transform:translateX(-50%) translateY(20px)}}100%{{opacity:1;transform:translateX(-50%) translateY(0)}}}}
#headline-box h2{{color:#fff;font-size:42px;font-weight:800;line-height:1.3;text-transform:uppercase;letter-spacing:1px;text-shadow:0 2px 10px rgba(0,0,0,0.8)}}
#location-tag{{display:inline-block;margin-top:16px;background:{c["glow"]};color:#fff;font-size:22px;font-weight:700;padding:6px 18px;border-radius:6px;letter-spacing:1px}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <svg id="map-bg" viewBox="0 0 2160 1080" preserveAspectRatio="xMidYMid slice">
    <defs>
      <pattern id="noise" width="100" height="100" patternUnits="userSpaceOnUse">
        <filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.6" numOctaves="3" stitchTiles="stitch"/></filter>
        <rect width="100" height="100" filter="url(#n)" opacity="0.06"/>
      </pattern>
      <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="4" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <rect width="2160" height="1080" fill="#0a0a0a"/>
    <rect width="2160" height="1080" fill="url(#noise)"/>
    <path fill="none" stroke="#222" stroke-width="0.8" d="{path_d or ""}"/>
  </svg>
  <div id="vignette"></div>
  <svg id="india-outline" viewBox="0 0 2160 1080" preserveAspectRatio="xMidYMid slice">
    <path d="{path_d or ""}"/>
  </svg>
  <div id="frame-wrap">
    <div id="photo-frame">
      <img src="data:image/jpeg;base64,{photo_b64 or ""}" alt=""/>
    </div>
  </div>
  <div id="connector"></div>
  <div id="num-circle"><span>{number}</span></div>
  <div id="headline-box">
    <h2>{safe_headline}</h2>
    <div id="location-tag">{safe_location}</div>
  </div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 3: ARTICLE CARD (floating article card over blurred background)
# ------------------------------------------------------------------
def article_card_html(masthead, headline, category, date_str, bg_b64, dur, source_color="#c00"):
    safe_masthead = _html.escape(masthead or "NEWS SOURCE").upper()
    safe_headline = _html.escape(headline or "HEADLINE")
    safe_category = _html.escape(category or "NEWS").upper()
    safe_date = _html.escape(date_str or _date_str())
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0}}
#bg{{position:absolute;inset:-80px;width:1240px;height:2080px;object-fit:cover;filter:blur(20px) brightness(0.35) saturate(0.7);animation:kb {dur:.2f}s linear forwards}}
@keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.08)}}}}
#vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center, transparent 20%, rgba(0,0,0,0.5) 100%);pointer-events:none}}
#card{{position:absolute;top:50%;left:50%;width:920px;transform:translate(-50%,-50%) rotate(-1deg);background:#fff;box-shadow:0 40px 100px rgba(0,0,0,0.9), 0 0 0 1px rgba(255,255,255,0.1);animation:cardIn 0.5s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes cardIn{{0%{{opacity:0;transform:translate(-50%,-50%) rotate(-3deg) scale(0.92)}}100%{{opacity:1;transform:translate(-50%,-50%) rotate(-1deg) scale(1)}}}}
#masthead{{padding:30px 40px 20px;border-bottom:3px solid #111;display:flex;justify-content:space-between;align-items:center}}
#masthead h1{{font-family:Georgia,serif;font-size:44px;font-weight:700;letter-spacing:1px;color:#111}}
#masthead .app-btn{{background:#c00;color:#fff;font:600 18px Arial;border-radius:6px;padding:8px 16px;letter-spacing:0.5px}}
#nav{{padding:14px 40px;color:#666;font-size:22px;letter-spacing:0.5px;border-bottom:1px solid #eee}}
#nav span{{margin-right:24px}}
#headline{{padding:30px 40px}}
#headline h2{{font-size:52px;font-weight:800;line-height:1.25;color:#111;letter-spacing:-0.5px}}
#meta{{padding:0 40px 30px;display:flex;align-items:center;gap:16px}}
#meta .tag{{border:2px solid #999;border-radius:999px;padding:5px 18px;color:#444;font-size:20px;font-weight:600}}
#meta .source-info{{color:#777;font-size:20px}}
#accent-bar{{height:6px;background:linear-gradient(90deg, {source_color}, #ff6b6b);width:100%}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <img id="bg" src="data:image/jpeg;base64,{bg_b64 or ""}" alt=""/>
  <div id="vignette"></div>
  <div id="card">
    <div id="masthead">
      <h1>{safe_masthead}</h1>
      <span class="app-btn">Download App</span>
    </div>
    <div id="nav">
      <span>News</span><span>Videos</span><span>India</span><span>World</span><span>City</span>
    </div>
    <div id="headline">
      <h2>{safe_headline}</h2>
    </div>
    <div id="meta">
      <span class="tag">{safe_category}</span>
      <span class="source-info">{safe_masthead} | {safe_date}</span>
    </div>
    <div id="accent-bar"></div>
  </div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 4: LOCATION HIGHLIGHT
# ------------------------------------------------------------------
def location_highlight_html(country, location, photo_b64, overlay_text, dur, theme="red"):
    colors = {
        "red": {"glow": "#dc2626", "glow2": "#991b1b", "fill": "#7f1d1d"},
        "purple": {"glow": "#c026d3", "glow2": "#7c3aed", "fill": "#581c87"},
        "blue": {"glow": "#2563eb", "glow2": "#1e40af", "fill": "#1e3a5f"},
    }
    c = colors.get(theme, colors["red"])
    path_d, cx, cy = get_country_path(country) or get_country_path("India") or ("", 78.0, 22.0)
    safe_text = _html.escape(overlay_text or location or "LOCATION")
    safe_loc = _html.escape(location or "LOCATION")
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0;animation:zoomIn {dur:.2f}s ease-out forwards}}
@keyframes zoomIn{{from{{transform:scale(1.3)}}to{{transform:scale(1)}}}}
#map-bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(0.8) brightness(0.15) contrast(1.3)}}
#vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center, transparent 25%, rgba(0,0,0,0.7) 100%);pointer-events:none}}
#country-outline{{position:absolute;inset:0;width:100%;height:100%}}
#country-outline path{{fill:url(#locGrad);stroke:#fff;stroke-width:2;filter:url(#locGlow);animation:pulseLoc 2.5s ease-in-out infinite}}
@keyframes pulseLoc{{0%,100%{{opacity:0.9}}50%{{opacity:1;filter:url(#locGlowBright)}}}}
#photo-wrap{{position:absolute;top:28%;left:50%;transform:translateX(-50%);width:700px;height:500px;animation:photoIn 0.6s 0.3s ease-out forwards;opacity:0;z-index:20}}
@keyframes photoIn{{0%{{opacity:0;transform:translateX(-50%) scale(0.85) rotate(-3deg)}}100%{{opacity:1;transform:translateX(-50%) scale(1) rotate(-1deg)}}}}
#photo-wrap img{{width:100%;height:100%;object-fit:cover;border:3px solid rgba(255,255,255,0.3);box-shadow:0 20px 60px rgba(0,0,0,0.9)}}
#photo-wrap::after{{content:'';position:absolute;inset:0;box-shadow:inset 0 0 40px rgba(0,0,0,0.5);pointer-events:none}}
#loc-label{{position:absolute;top:62%;left:50%;transform:translateX(-50%);background:{c["glow"]};color:#fff;font-weight:900;font-size:42px;padding:12px 32px;border-radius:8px;letter-spacing:2px;text-transform:uppercase;box-shadow:0 0 40px {c["glow"]}, 0 10px 30px rgba(0,0,0,0.5);animation:labelIn 0.5s 0.6s ease-out forwards;opacity:0;z-index:20}}
@keyframes labelIn{{0%{{opacity:0;transform:translateX(-50%) translateY(20px)}}100%{{opacity:1;transform:translateX(-50%) translateY(0)}}}}
#overlay-text{{position:absolute;bottom:180px;left:0;width:100%;text-align:center;color:#fff;font-weight:800;font-size:48px;letter-spacing:1px;text-shadow:0 4px 20px rgba(0,0,0,0.9);padding:0 80px;line-height:1.3;animation:textIn 0.6s 0.8s ease-out forwards;opacity:0}}
@keyframes textIn{{0%{{opacity:0;transform:translateY(30px)}}100%{{opacity:1;transform:translateY(0)}}}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <svg id="map-bg" viewBox="0 0 2160 1080" preserveAspectRatio="xMidYMid slice">
    <defs>
      <pattern id="noise" width="100" height="100" patternUnits="userSpaceOnUse">
        <filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.6" numOctaves="3" stitchTiles="stitch"/></filter>
        <rect width="100" height="100" filter="url(#n)" opacity="0.06"/>
      </pattern>
      <linearGradient id="locGrad" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="{c["glow"]}"/>
        <stop offset="100%" stop-color="{c["glow2"]}"/>
      </linearGradient>
      <filter id="locGlow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="8" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <filter id="locGlowBright" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="15" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <rect width="2160" height="1080" fill="#0a0a0a"/>
    <rect width="2160" height="1080" fill="url(#noise)"/>
    <path fill="none" stroke="#222" stroke-width="0.8" d="{path_d or ""}"/>
  </svg>
  <div id="vignette"></div>
  <svg id="country-outline" viewBox="0 0 2160 1080" preserveAspectRatio="xMidYMid slice">
    <path d="{path_d or ""}"/>
  </svg>
  <div id="photo-wrap">
    <img src="data:image/jpeg;base64,{photo_b64 or ""}" alt=""/>
  </div>
  <div id="loc-label">{safe_loc}</div>
  <div id="overlay-text">{safe_text}</div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 5: DISASTER DRAMATIC
# ------------------------------------------------------------------
def disaster_dramatic_html(headline, sub_text, footage_b64, dur):
    safe_headline = _html.escape(headline or "BREAKING").upper()
    safe_sub = _html.escape(sub_text or "")
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(0.4) contrast(1.2);animation:shake 0.3s ease-in-out}}
@keyframes shake{{0%,100%{{transform:translate(0)}}25%{{transform:translate(-2px,1px)}}75%{{transform:translate(2px,-1px)}}}}
#red-overlay{{position:absolute;inset:0;background:linear-gradient(180deg, rgba(180,0,0,0.5) 0%, rgba(120,0,0,0.7) 50%, rgba(80,0,0,0.8) 100%);mix-blend-mode:multiply;animation:redPulse 3s ease-in-out infinite}}
@keyframes redPulse{{0%,100%{{opacity:0.85}}50%{{opacity:1}}}}
#vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center, transparent 30%, rgba(0,0,0,0.8) 100%);pointer-events:none}}
#alert-bar{{position:absolute;top:0;left:0;width:100%;height:8px;background:linear-gradient(90deg, #ff0000, #ff4444, #ff0000);animation:alertFlash 1s ease-in-out infinite}}
@keyframes alertFlash{{0%,100%{{opacity:1}}50%{{opacity:0.6}}}}
#headline-wrap{{position:absolute;top:50%;left:0;width:100%;transform:translateY(-50%);text-align:center;padding:0 60px;animation:textIn 0.7s ease-out forwards;opacity:0}}
@keyframes textIn{{0%{{opacity:0;transform:translateY(-50%) scale(0.9)}}100%{{opacity:1;transform:translateY(-50%) scale(1)}}}}
#headline-wrap h1{{color:#fff;font-size:72px;font-weight:900;line-height:1.15;text-transform:uppercase;letter-spacing:2px;text-shadow:0 4px 30px rgba(0,0,0,0.9), 0 0 60px rgba(255,0,0,0.5);margin-bottom:20px}}
#headline-wrap .sub{{color:#ffaaaa;font-size:36px;font-weight:700;letter-spacing:1px;text-shadow:0 2px 15px rgba(0,0,0,0.8);line-height:1.4}}
#bottom-info{{position:absolute;bottom:120px;left:0;width:100%;text-align:center;animation:bottomIn 0.5s 0.4s ease-out forwards;opacity:0}}
@keyframes bottomIn{{0%{{opacity:0;transform:translateY(20px)}}100%{{opacity:1;transform:translateY(0)}}}}
#bottom-info .badge{{display:inline-block;background:#ff0000;color:#fff;font-size:24px;font-weight:900;padding:8px 24px;border-radius:4px;letter-spacing:2px;text-transform:uppercase;box-shadow:0 0 30px rgba(255,0,0,0.6)}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <img id="bg" src="data:image/jpeg;base64,{footage_b64 or ""}" alt=""/>
  <div id="red-overlay"></div>
  <div id="vignette"></div>
  <div id="alert-bar"></div>
  <div id="headline-wrap">
    <h1>{safe_headline}</h1>
    <div class="sub">{safe_sub}</div>
  </div>
  <div id="bottom-info">
    <span class="badge">BREAKING NEWS</span>
  </div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 6: FOOTAGE HIGHLIGHT (red circle emphasis)
# ------------------------------------------------------------------
def footage_highlight_html(footage_b64, circle_x=540, circle_y=960, circle_r=200, label_text="", dur=5):
    safe_label = _html.escape(label_text or "")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
#highlight{{position:absolute;left:{circle_x-circle_r}px;top:{circle_y-circle_r}px;width:{circle_r*2}px;height:{circle_r*2}px;pointer-events:none}}
#highlight svg{{width:100%;height:100%;overflow:visible}}
#highlight circle{{fill:none;stroke:#ff0000;stroke-width:6;stroke-dasharray:20 10;animation:dashSpin 8s linear infinite, circlePulse 2s ease-in-out infinite}}
@keyframes dashSpin{{0%{{stroke-dashoffset:0}}100%{{stroke-dashoffset:-300}}}}
@keyframes circlePulse{{0%,100%{{stroke-width:6;filter:drop-shadow(0 0 10px rgba(255,0,0,0.8))}}50%{{stroke-width:8;filter:drop-shadow(0 0 25px rgba(255,0,0,1))}}}}
.crosshair{{position:absolute;background:rgba(255,0,0,0.4);pointer-events:none}}
.ch-h{{height:2px;width:60px;left:50%;transform:translateX(-50%)}}
.ch-v{{width:2px;height:60px;top:50%;transform:translateY(-50%)}}
.ch-t{{top:{circle_y-circle_r-30}px}}
.ch-b{{top:{circle_y+circle_r+28}px}}
.ch-l{{left:{circle_x-circle_r-30}px}}
.ch-r{{left:{circle_x+circle_r+28}px}}
#label{{position:absolute;left:50%;top:{circle_y+circle_r+60}px;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#ff4444;font-size:28px;font-weight:800;padding:10px 24px;border-radius:6px;border:2px solid #ff4444;letter-spacing:1px;animation:labelIn 0.5s 0.3s ease-out forwards;opacity:0;white-space:nowrap}}
@keyframes labelIn{{0%{{opacity:0;transform:translateX(-50%) translateY(-10px)}}100%{{opacity:1;transform:translateX(-50%) translateY(0)}}}}
#mask{{position:absolute;inset:0;pointer-events:none}}
#mask svg{{width:100%;height:100%}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <img id="bg" src="data:image/jpeg;base64,{footage_b64 or ""}" alt=""/>
  <div id="mask">
    <svg width="1080" height="1920">
      <defs>
        <mask id="circleMask">
          <rect width="1080" height="1920" fill="white"/>
          <circle cx="{circle_x}" cy="{circle_y}" r="{circle_r}" fill="black"/>
        </mask>
      </defs>
      <rect width="1080" height="1920" fill="rgba(0,0,0,0.35)" mask="url(#circleMask)"/>
    </svg>
  </div>
  <div id="highlight">
    <svg viewBox="0 0 {circle_r*2} {circle_r*2}">
      <circle cx="{circle_r}" cy="{circle_r}" r="{circle_r-5}"/>
    </svg>
  </div>
  <div class="crosshair ch-h ch-t"></div>
  <div class="crosshair ch-h ch-b"></div>
  <div class="crosshair ch-v ch-l"></div>
  <div class="crosshair ch-v ch-r"></div>
  {f'<div id="label">{safe_label}</div>' if safe_label else ''}
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 7: BREAKING CARD
# ------------------------------------------------------------------
def breaking_card_html(headline, sub, img_b64, dur, source=""):
    safe_headline = _html.escape(headline or "BREAKING NEWS").upper()
    safe_sub = _html.escape(sub or "")
    safe_source = _html.escape(source or "")
    words = safe_headline.split()
    k = min(4, len(words))
    hl_words = " ".join(words[:k])
    rest_words = " ".join(words[k:])
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#111;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0}}
#bg-anim{{position:absolute;inset:0;background:linear-gradient(135deg, #1a1a1a 0%, #0a0a0a 50%, #1a0a0a 100%);animation:bgShift 8s ease-in-out infinite}}
@keyframes bgShift{{0%,100%{{background-position:0% 50%}}50%{{background-position:100% 50%}}}}
.accent-line{{position:absolute;height:3px;background:linear-gradient(90deg, transparent, #ff0000, transparent);animation:linePulse 2s ease-in-out infinite}}
.al1{{top:200px;left:0;width:100%}}
.al2{{bottom:200px;left:0;width:100%}}
@keyframes linePulse{{0%,100%{{opacity:0.3}}50%{{opacity:0.8}}}}
#card{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:950px;background:#fff;box-shadow:0 50px 100px rgba(0,0,0,0.9), 0 0 0 1px rgba(255,255,255,0.1);animation:cardIn 0.5s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes cardIn{{0%{{opacity:0;transform:translate(-50%,-50%) scale(0.9) rotate(-2deg)}}100%{{opacity:1;transform:translate(-50%,-50%) scale(1) rotate(0deg)}}}}
#breaking{{padding:35px 45px 15px;font-size:130px;font-weight:900;letter-spacing:-3px;color:#000;line-height:0.9;animation:breakIn 0.4s 0.2s ease-out forwards;opacity:0}}
@keyframes breakIn{{0%{{opacity:0;transform:translateX(-30px)}}100%{{opacity:1;transform:translateX(0)}}}}
#hl{{padding:0 45px 20px;font-size:54px;font-weight:800;line-height:1.2;color:#000;letter-spacing:-0.5px}}
#hl .red{{background:#d40000;color:#fff;padding:2px 10px;margin-right:4px}}
#sub{{padding:0 45px 25px;font-size:28px;color:#444;font-weight:600}}
#img-wrap{{width:100%;height:720px;overflow:hidden;position:relative}}
#img-wrap img{{width:100%;height:100%;object-fit:cover}}
#img-wrap::after{{content:'';position:absolute;inset:0;background:linear-gradient(to top, rgba(0,0,0,0.4) 0%, transparent 40%);pointer-events:none}}
#source-badge{{position:absolute;bottom:40px;left:45px;background:#c00;color:#fff;font-weight:900;font-size:32px;padding:10px 24px;letter-spacing:1px;box-shadow:0 4px 20px rgba(0,0,0,0.5)}}
#date-badge{{position:absolute;bottom:40px;right:45px;background:#111;color:#fff;font-weight:800;font-size:26px;padding:10px 20px}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <div id="bg-anim"></div>
  <div class="accent-line al1"></div>
  <div class="accent-line al2"></div>
  <div id="card">
    <div id="breaking">BREAKING</div>
    <div id="hl"><span class="red">{hl_words}</span> {rest_words}</div>
    <div id="sub">{safe_sub}</div>
    <div id="img-wrap">
      <img src="data:image/jpeg;base64,{img_b64 or ""}" alt=""/>
      <div id="source-badge">{safe_source or "LIVE UPDATE"}</div>
      <div id="date-badge">{_date_str()}</div>
    </div>
  </div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 8: QUOTE CARD
# ------------------------------------------------------------------
def quote_card_html(quote_text, person, dur, theme="purple"):
    colors = {
        "purple": {"accent": "#c026d3", "bg": "#0a0a0a"},
        "red": {"accent": "#dc2626", "bg": "#0a0505"},
        "blue": {"accent": "#2563eb", "bg": "#050a0a"},
    }
    c = colors.get(theme, colors["purple"])
    safe_quote = _html.escape(quote_text or "")
    safe_person = _html.escape(person or "")
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:{c["bg"]};overflow:hidden;font-family:Georgia,serif}}
#wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:80px}}
#quote-mark{{position:absolute;top:120px;left:60px;font-size:280px;color:{c["accent"]};opacity:0.15;font-family:Georgia,serif;line-height:1;animation:markIn 0.6s ease-out forwards;opacity:0}}
@keyframes markIn{{0%{{opacity:0;transform:scale(0.5)}}100%{{opacity:0.15;transform:scale(1)}}}}
#card{{width:100%;background:linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.03) 100%);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:60px;backdrop-filter:blur(20px);box-shadow:0 30px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.1);animation:cardIn 0.5s ease-out forwards;opacity:0}}
@keyframes cardIn{{0%{{opacity:0;transform:translateY(30px)}}100%{{opacity:1;transform:translateY(0)}}}}
#quote{{font-size:44px;line-height:1.5;color:#f0f0f0;font-style:italic;text-shadow:0 2px 10px rgba(0,0,0,0.5)}}
#quote::before{{content:'"';color:{c["accent"]};font-size:60px;font-weight:900;margin-right:8px;vertical-align:-10px}}
#quote::after{{content:'"';color:{c["accent"]};font-size:60px;font-weight:900;margin-left:8px;vertical-align:-10px}}
#person{{margin-top:40px;padding-top:30px;border-top:2px solid {c["accent"]};display:flex;align-items:center;gap:20px}}
#person-avatar{{width:70px;height:70px;border-radius:50%;background:linear-gradient(135deg, {c["accent"]}, #333);display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px;font-weight:900;font-family:Arial}}
#person-name{{color:#fff;font-size:32px;font-weight:700;font-family:Arial}}
#person-title{{color:#aaa;font-size:22px;font-family:Arial;margin-top:4px}}
#glow{{position:absolute;bottom:200px;right:100px;width:300px;height:300px;border-radius:50%;background:radial-gradient(circle, {c["accent"]}40 0%, transparent 70%);filter:blur(60px);animation:glowPulse 4s ease-in-out infinite}}
@keyframes glowPulse{{0%,100%{{opacity:0.5;transform:scale(1)}}50%{{opacity:0.8;transform:scale(1.2)}}}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <div id="quote-mark">"</div>
  <div id="glow"></div>
  <div id="card">
    <div id="quote">{safe_quote}</div>
    <div id="person">
      <div id="person-avatar">{safe_person[0] if safe_person else "?"}</div>
      <div>
        <div id="person-name">{safe_person}</div>
        <div id="person-title">Official Statement</div>
      </div>
    </div>
  </div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 9: OUTRO
# ------------------------------------------------------------------
def outro_html(dur=4):
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}}
#particles{{position:absolute;inset:0;overflow:hidden}}
.particle{{position:absolute;width:4px;height:4px;background:rgba(255,255,255,0.3);border-radius:50%;animation:float linear infinite}}
@keyframes float{{0%{{transform:translateY(1920px) rotate(0deg);opacity:0}}10%{{opacity:1}}90%{{opacity:1}}100%{{transform:translateY(-100px) rotate(720deg);opacity:0}}}}
#card{{width:800px;background:linear-gradient(180deg, #1a1a1a 0%, #0d0d0d 100%);border-radius:30px;padding:60px 50px;border:1px solid rgba(255,255,255,0.08);box-shadow:0 40px 100px rgba(0,0,0,0.8);animation:cardIn 0.6s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0;z-index:10}}
@keyframes cardIn{{0%{{opacity:0;transform:scale(0.9) translateY(30px)}}100%{{opacity:1;transform:scale(1) translateY(0)}}}}
#avatar-row{{display:flex;align-items:center;gap:30px;margin-bottom:50px}}
#avatar{{width:150px;height:150px;border-radius:50%;background:linear-gradient(45deg, #feda75, #fa7e1e, #d62976, #962fbf, #4f5bd5);padding:6px;animation:avatarGlow 3s ease-in-out infinite}}
@keyframes avatarGlow{{0%,100%{{box-shadow:0 0 30px rgba(214,41,118,0.3)}}50%{{box-shadow:0 0 60px rgba(214,41,118,0.6)}}}}
#avatar-inner{{width:100%;height:100%;border-radius:50%;background:#000;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:52px;font-family:Arial}}
#name{{color:#fff;font-size:48px;font-weight:800}}
#handle{{color:#888;font-size:28px;margin-top:6px}}
#verified{{display:inline-flex;align-items:center;gap:8px;margin-top:10px}}
#verified svg{{width:28px;height:28px}}
#verified span{{color:#3897f0;font-size:24px;font-weight:700}}
#btn-wrap{{position:relative;height:100px;margin-top:20px}}
#follow-btn{{position:absolute;left:0;right:0;top:0;background:#3897ef;color:#fff;text-align:center;font-weight:800;font-size:38px;padding:28px;border-radius:16px;animation:btnFlip1 2s ease-in-out infinite}}
@keyframes btnFlip1{{0%,45%{{opacity:1}}55%,100%{{opacity:0}}}}
#following-btn{{position:absolute;left:0;right:0;top:0;background:#eee;color:#555;text-align:center;font-weight:800;font-size:38px;padding:28px;border-radius:16px;opacity:0;animation:btnFlip2 2s ease-in-out infinite}}
@keyframes btnFlip2{{0%,45%{{opacity:0}}55%,100%{{opacity:1}}}}
#ig-logo{{margin-top:60px;animation:logoIn 1s 0.8s ease-out forwards;opacity:0}}
@keyframes logoIn{{0%{{opacity:0;transform:scale(0.5)}}100%{{opacity:1;transform:scale(1)}}}}
#ig-logo svg{{width:120px;height:120px}}
#big-handle{{margin-top:30px;color:#fff;font-size:42px;font-weight:800;letter-spacing:2px;animation:handleIn 0.8s 1s ease-out forwards;opacity:0}}
@keyframes handleIn{{0%{{opacity:0;transform:translateY(20px)}}100%{{opacity:1;transform:translateY(0)}}}}
{LOGO_SVG}
</style></head><body>
<div id="wrap">
  <div id="particles">
    <div class="particle" style="left:10%;animation-duration:12s;animation-delay:0s"></div>
    <div class="particle" style="left:25%;animation-duration:15s;animation-delay:2s"></div>
    <div class="particle" style="left:40%;animation-duration:10s;animation-delay:1s"></div>
    <div class="particle" style="left:55%;animation-duration:14s;animation-delay:3s"></div>
    <div class="particle" style="left:70%;animation-duration:11s;animation-delay:0.5s"></div>
    <div class="particle" style="left:85%;animation-duration:13s;animation-delay:2.5s"></div>
    <div class="particle" style="left:15%;animation-duration:16s;animation-delay:4s"></div>
    <div class="particle" style="left:90%;animation-duration:9s;animation-delay:1.5s"></div>
  </div>
  <div id="card">
    <div id="avatar-row">
      <div id="avatar"><div id="avatar-inner">24</div></div>
      <div>
        <div id="name">indiainlast24hr</div>
        <div id="handle">@INDIAINLAST24HR</div>
        <div id="verified">
          <svg viewBox="0 0 24 24" fill="#3897f0"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
          <span>Verified</span>
        </div>
      </div>
    </div>
    <div id="btn-wrap">
      <div id="follow-btn">Follow</div>
      <div id="following-btn">Following &#9662;</div>
    </div>
  </div>
  <div id="ig-logo">
    <svg viewBox="0 0 24 24" fill="none" stroke="url(#igGrad)" stroke-width="1.5">
      <defs><linearGradient id="igGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#feda75"/><stop offset="25%" stop-color="#fa7e1e"/><stop offset="50%" stop-color="#d62976"/><stop offset="75%" stop-color="#962fbf"/><stop offset="100%" stop-color="#4f5bd5"/></linearGradient></defs>
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5"/>
      <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/>
      <line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/>
    </svg>
  </div>
  <div id="big-handle">@INDIAINLAST24HR</div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# SCENE 10: STAT OVERLAY
# ------------------------------------------------------------------
def stat_overlay_html(stat_text, label, bg_b64, dur, theme="purple"):
    colors = {
        "purple": {"glow": "#c026d3", "accent": "#e879f9"},
        "red": {"glow": "#dc2626", "accent": "#f87171"},
        "blue": {"glow": "#2563eb", "accent": "#60a5fa"},
        "gold": {"glow": "#f59e0b", "accent": "#fbbf24"},
    }
    c = colors.get(theme, colors["purple"])
    safe_stat = _html.escape(stat_text or "0")
    safe_label = _html.escape(label or "")
    
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0}}
#bg{{position:absolute;inset:-60px;width:1200px;height:2040px;object-fit:cover;filter:blur(15px) brightness(0.25) saturate(0.6);animation:kb {dur:.2f}s linear forwards}}
@keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.1)}}}}
#vignette{{position:absolute;inset:0;background:radial-gradient(ellipse at center, transparent 20%, rgba(0,0,0,0.6) 100%);pointer-events:none}}
#stat-wrap{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;animation:statIn 0.7s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes statIn{{0%{{opacity:0;transform:translate(-50%,-50%) scale(0.5)}}100%{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
#stat-circle{{width:500px;height:500px;border-radius:50%;background:linear-gradient(135deg, rgba(0,0,0,0.8), rgba(0,0,0,0.6));border:4px solid {c["glow"]};display:flex;flex-direction:column;align-items:center;justify-content:center;box-shadow:0 0 80px {c["glow"]}40, 0 0 150px {c["glow"]}20, inset 0 0 60px {c["glow"]}10;animation:circlePulse 3s ease-in-out infinite}}
@keyframes circlePulse{{0%,100%{{box-shadow:0 0 80px {c["glow"]}40, 0 0 150px {c["glow"]}20, inset 0 0 60px {c["glow"]}10}}50%{{box-shadow:0 0 120px {c["glow"]}60, 0 0 200px {c["glow"]}30, inset 0 0 80px {c["glow"]}20}}}}
#stat-num{{color:#fff;font-size:120px;font-weight:900;font-family:Arial Black;text-shadow:0 0 40px {c["glow"]}, 0 4px 20px rgba(0,0,0,0.8);line-height:1}}
#stat-label{{color:{c["accent"]};font-size:36px;font-weight:800;margin-top:16px;letter-spacing:3px;text-transform:uppercase}}
{LOGO_SVG}
{HANDLE_HTML}
</style></head><body>
<div id="wrap">
  <img id="bg" src="data:image/jpeg;base64,{bg_b64 or ""}" alt=""/>
  <div id="vignette"></div>
  <div id="stat-wrap">
    <div id="stat-circle">
      <div id="stat-num">{safe_stat}</div>
      <div id="stat-label">{safe_label}</div>
    </div>
  </div>
</div>
</body></html>"""

# ------------------------------------------------------------------
# LEGACY COMPATIBILITY
# ------------------------------------------------------------------
def map_html(country, pin, overlay_text, dur, lat=None, lon=None, topic_img=None):
    """Legacy wrapper - now uses the new dramatic map intro."""
    return map_intro_html(country, overlay_text, dur, theme="purple", topic_img=topic_img, pin=pin)

def shot_card_html(shot_path, bg_path, source, dur):
    """Legacy wrapper - now uses article card."""
    return article_card_html(source, "BREAKING NEWS", "NEWS", _date_str(), bg_path, dur)

def breaking_html(headline, sub, img_path, dur):
    """Legacy wrapper - now uses breaking card."""
    img_b64 = _b64_or_empty(img_path)
    return breaking_card_html(headline, sub, img_b64, dur)

def quote_html(text, person, timings, dur):
    """Legacy wrapper - now uses quote card."""
    return quote_card_html(text, person, dur)

def outro_video():
    """Generate outro video."""
    cache = Path(settings.output_dir) / "outro.mp4"
    if cache.exists():
        return str(cache)
    webm = record_html(outro_html(4), 4, "outro")
    import imageio_ffmpeg as ioff, subprocess
    subprocess.run([ioff.get_ffmpeg_exe(), "-y", "-i", webm, "-vf", "fps=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cache)], check=True, capture_output=True)
    return str(cache)