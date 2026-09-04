import html as _html, os, base64, datetime, json, re
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from .config import settings

RAW = Path(settings.output_dir).resolve() / "raw"

# ---------------- utilities ----------------
def _date_str():
    ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b").upper()

def _b64_or_empty(p):
    if p and os.path.exists(p):
        return base64.b64encode(Path(p).read_bytes()).decode()
    return ""

def record_html(page_html, dur, name, viewport=(1080, 1920)):
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}.html"
    p.write_text(page_html, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--allow-file-access-from-files"])
        ctx = b.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                            record_video_dir=str(RAW),
                            record_video_size={"width": viewport[0], "height": viewport[1]})
        pg = ctx.new_page()
        pg.goto(p.resolve().as_uri())
        pg.wait_for_timeout(int(dur * 1000))
        v = pg.video
        pg.close(); out = v.path(); ctx.close(); b.close()
    return out

# ---------------- India-centred projector ----------------
def _sx(lo): return (lo - 66.0) * 31.8
def _sy(la): return 420.0 + (38.0 - la) * 31.8

_INDIA_FALLBACK = [
    (68.2,23.6),(69.5,22.4),(70.6,20.7),(72.7,19.0),(73.6,16.0),(74.9,12.8),
    (76.1,10.2),(77.5,8.1),(79.9,10.2),(80.3,13.5),(82.6,17.0),(85.1,19.6),
    (87.0,21.4),(88.1,21.7),(88.2,24.4),(88.6,26.1),(90.1,25.2),(92.1,25.0),
    (94.6,26.6),(96.6,28.4),(97.1,27.8),(94.2,29.3),(91.1,27.8),(88.6,27.1),
    (85.1,27.4),(84.1,28.6),(80.1,30.6),(78.1,31.6),(76.1,32.6),(74.4,34.1),
    (73.9,35.9),(76.1,35.4),(78.1,34.4),(79.6,32.9),(78.4,31.2),(75.4,31.0),
    (74.6,29.4),(73.4,27.9),(71.9,27.9),(70.7,26.0),(69.6,24.3),(68.2,23.6)]

def _india_fallback_path():
    return "M" + "L".join(f"{_sx(lo):.0f} {_sy(la):.0f}" for lo, la in _INDIA_FALLBACK) + "Z"

# ---------------- geojson ----------------
def _geojson():
    if not hasattr(_geojson, "cache"):
        cf = Path(settings.output_dir).resolve() / "cache_countries.geojson"
        data = None
        try:
            if cf.exists(): data = json.loads(cf.read_text(encoding="utf-8"))
        except Exception: data = None
        if not data or not data.get("features"):
            for url in ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson",
                        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"):
                try:
                    data = httpx.get(url, timeout=120).json()
                    if data.get("features"): break
                except Exception: continue
            try:
                if data and data.get("features"):
                    cf.parent.mkdir(parents=True, exist_ok=True); cf.write_text(json.dumps(data), encoding="utf-8")
            except Exception: pass
        _geojson.cache = data if data and data.get("features") else {"features": []}
    return _geojson.cache

def has_country(name):
    if not name: return False
    n = name.lower()
    return any(n == (f["properties"].get("NAME") or "").lower() or n in (f["properties"].get("NAME") or "").lower()
               for f in _geojson()["features"])

def _rings_of(geom, max_rings=3, step=2):
    if geom.get("type") == "MultiPolygon": rings = [p[0] for p in geom.get("coordinates", [])]
    elif geom.get("type") == "Polygon": rings = [geom.get("coordinates", [[]])[0]]
    else: return []
    return [r[::step] for r in sorted(rings, key=len, reverse=True)[:max_rings]]

def get_country_path(name):
    gj = _geojson()["features"]
    nm = lambda f: (f["properties"].get("NAME") or "").lower()
    t = next((f for f in gj if nm(f) == (name or "").lower()), None)
    if t is None: t = next((f for f in gj if (name or "").lower() in nm(f)), None)
    if t is None:
        if name and "india" in name.lower(): return _india_fallback_path(), 540.0, 960.0
        return None, None, None
    d = "".join("M" + "L".join(f"{_sx(c[0]):.0f} {_sy(c[1]):.0f}" for c in r) + "Z"
                for r in _rings_of(t["geometry"], 6, 2))
    return d, 540.0, 960.0

def _states_geojson():
    if not hasattr(_states_geojson, "cache"):
        cf = Path(settings.output_dir).resolve() / "cache_states.geojson"
        try:
            if cf.exists():
                _states_geojson.cache = json.loads(cf.read_text(encoding="utf-8"))
            else:
                data = {"features": []}
                try:
                    data = httpx.get(_STATE_URL, timeout=120).json()
                    if data.get("features"):
                        cf.write_text(json.dumps(data), encoding="utf-8")
                except Exception: pass
                _states_geojson.cache = data
        except Exception:
            _states_geojson.cache = {"features": []}
    return _states_geojson.cache

_STATE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson"

def _feat_name(f):
    p = f.get("properties", {}) or {}
    for k in ("name", "NAME", "NAME_1", "NAME_EN", "shapeName", "st_nm"):
        if p.get(k): return str(p[k]).lower()
    return ""

def _is_india_state(f):
    p = f.get("properties", {}) or {}
    return p.get("admin") == "India" or p.get("iso_a2") == "IN"

def get_state_path(name):
    if not name: return None
    gj = _states_geojson().get("features", [])
    n = name.lower().strip()
    t = next((f for f in gj if _is_india_state(f) and _feat_name(f) == n), None)
    if t is None:
        t = next((f for f in gj if _is_india_state(f) and n and (n in _feat_name(f) or _feat_name(f) in n)), None)
    if t is None: return None
    return "".join("M" + "L".join(f"{_sx(c[0]):.0f} {_sy(c[1]):.0f}" for c in r) + "Z"
                   for r in _rings_of(t["geometry"], 3, 2))

def get_state_centroid(name):
    if not name: return (540.0, 930.0)
    gj = _states_geojson().get("features", [])
    n = name.lower().strip()
    t = next((f for f in gj if _is_india_state(f) and _feat_name(f) == n), None)
    if t is None:
        t = next((f for f in gj if _is_india_state(f) and n and (n in _feat_name(f) or _feat_name(f) in n)), None)
    if t is None: return (540.0, 930.0)
    r = _rings_of(t["geometry"], 1, 1)
    if not r: return (540.0, 930.0)
    lo = sum(c[0] for c in r[0]) / len(r[0]); la = sum(c[1] for c in r[0]) / len(r[0])
    return (_sx(lo), _sy(la))

def _states_outline():
    if not hasattr(_states_outline, "cache"):
        parts = []
        for f in _states_geojson().get("features", []):
            if not _is_india_state(f): continue
            for r in _rings_of(f["geometry"], 2, 3):
                parts.append("M" + "L".join(f"{_sx(c[0]):.0f} {_sy(c[1]):.0f}" for c in r) + "Z")
        _states_outline.cache = "".join(parts)
    return _states_outline.cache

# ---------------- backgrounds ----------------
def get_satellite_b64():
    if not hasattr(get_satellite_b64, "cache"):
        b = _b64_or_empty(os.path.join("assets", "terrain.jpg")) or _b64_or_empty(os.path.join(settings.output_dir, "satellite.jpg"))
        if not b:
            try:
                from . import media
                if media.commons_image("India satellite terrain aerial", os.path.join(settings.output_dir, "satellite.jpg")):
                    b = _b64_or_empty(os.path.join(settings.output_dir, "satellite.jpg"))
            except Exception: pass
        get_satellite_b64.cache = b or ""
    return get_satellite_b64.cache

def _bg_layer(sat_b64, blur=0, bright=0.5):
    if sat_b64:
        f = f"filter:grayscale(1) brightness({bright}) contrast(1.25)" + (f" blur({blur}px)" if blur else "")
        return f'<img id="sat" src="data:image/jpeg;base64,{sat_b64}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;{f}"/>'
    # Fallback: Dark cloudy satellite look (NOT TV static)
    return '''<svg id="sat" style="position:absolute;inset:0;width:100%;height:100%" viewBox="0 0 1080 1920" preserveAspectRatio="xMidYMid slice">
      <defs>
        <filter id="terr" x="-20%" y="-20%" width="140%" height="140%"><feTurbulence type="fractalNoise" baseFrequency="0.004 0.006" numOctaves="5" seed="11" stitchTiles="stitch"/><feColorMatrix type="matrix" values="0 0 0 0 0.12  0 0 0 0 0.14  0 0 0 0 0.16  0 0 0 0.95 0"/><feGaussianBlur stdDeviation="3"/></filter>
        <radialGradient id="vig" cx="50%" cy="45%" r="75%"><stop offset="50%" stop-color="rgba(0,0,0,0)"/><stop offset="100%" stop-color="rgba(0,0,0,0.9)"/></radialGradient>
      </defs>
      <rect width="1080" height="1920" fill="#080a0c"/>
      <rect width="1080" height="1920" filter="url(#terr)"/>
      <rect width="1080" height="1920" fill="url(#vig)"/>
    </svg>'''

CLOUDS_CSS = """#clouds{position:absolute;inset:0;pointer-events:none;opacity:0.5}
.cloud{position:absolute;background:radial-gradient(ellipse, rgba(255,255,255,0.10) 0%, transparent 70%);border-radius:50%}
.c1{width:700px;height:340px;top:-60px;left:-120px;animation:drift1 20s infinite}
.c2{width:560px;height:280px;top:240px;right:-160px;animation:drift2 25s infinite}
.c3{width:760px;height:380px;bottom:-120px;left:180px;animation:drift1 30s infinite}
@keyframes drift1{0%,100%{transform:translateX(0)}50%{transform:translateX(90px)}}
@keyframes drift2{0%,100%{transform:translateX(0)}50%{transform:translateX(-70px)}}"""
CLOUDS_HTML = '<div id="clouds"><div class="cloud c1"></div><div class="cloud c2"></div><div class="cloud c3"></div></div>'

def _map_defs(c):
    return f"""<defs>
      <linearGradient id="countryGrad" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="{c['glow']}"/><stop offset="55%" stop-color="{c['glow2']}"/><stop offset="100%" stop-color="{c.get('glow3', c['glow2'])}"/>
      </linearGradient>
      <filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <filter id="glowBright" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="12" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <filter id="softGlow" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>"""

# ---------------- SCENE: title card ----------------
def title_card_html(text, dur, theme="purple"):
    g = {"purple": "#a21caf", "red": "#b91c1c", "blue": "#1d4ed8"}.get(theme, "#a21caf")
    safe = _html.escape(text or "BREAKING NEWS").upper()
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#glowbg{{position:absolute;left:50%;top:40%;width:900px;height:500px;transform:translate(-50%,-50%);background:radial-gradient(ellipse, {g}55 0%, transparent 70%);filter:blur(40px);animation:gp {dur:.2f}s ease-in-out infinite alternate}}
@keyframes gp{{from{{opacity:0.5;transform:translate(-50%,-50%) scale(1)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1.15)}}}}
#txt{{position:absolute;top:40%;left:0;width:100%;transform:translateY(-50%);text-align:center;color:#e8e8e8;font-weight:900;font-size:64px;line-height:1.35;letter-spacing:2px;padding:0 70px;text-shadow:0 2px 6px rgba(0,0,0,0.9), 0 0 40px {g};animation:zin {dur:.2f}s cubic-bezier(0.2,0.7,0.3,1) forwards}}
@keyframes zin{{0%{{opacity:0;transform:translateY(-50%) scale(0.85)}}25%{{opacity:1}}100%{{opacity:1;transform:translateY(-50%) scale(1.06)}}}}
</style></head><body><div id="glowbg"></div><div id="txt">{safe}</div></body></html>"""

# ---------------- SCENE: map intro (terrain + clouds + topic pin) ----------------
def map_intro_html(country, overlay_text, dur, theme="purple", topic_img=None, pin=None):
    colors = {"purple": {"glow": "#e815e8", "glow2": "#7c3aed", "glow3": "#2563eb"},
              "red": {"glow": "#dc2626", "glow2": "#991b1b", "glow3": "#7f1d1d"},
              "blue": {"glow": "#2563eb", "glow2": "#1e40af", "glow3": "#1e3a8a"}}
    c = colors.get(theme, colors["purple"])
    path_d, _, _ = get_country_path(country or "India") or (_india_fallback_path(), 0, 0)
    if not path_d: path_d = _india_fallback_path()
    outlines = _states_outline()
    sat = get_satellite_b64()
    pin_b64 = _b64_or_empty(topic_img)
    pin_html = f"""<div id="pinwrap"><svg id="arcs" width="600" height="600" viewBox="0 0 600 600">
      <path d="M300 300 C 180 220, 90 200, 10 160" stroke="#fff" stroke-width="3" fill="none" opacity="0.8"/>
      <path d="M300 300 C 420 220, 510 200, 590 160" stroke="#fff" stroke-width="3" fill="none" opacity="0.8"/>
      <path d="M300 300 C 200 400, 120 440, 40 480" stroke="#fff" stroke-width="3" fill="none" opacity="0.8"/>
      <path d="M300 300 C 400 400, 480 440, 560 480" stroke="#fff" stroke-width="3" fill="none" opacity="0.8"/>
    </svg>
    <div id="pinring"><img src="data:image/jpeg;base64,{pin_b64}"/></div>
    <div id="pinlabel">{_html.escape(pin or 'INDIA')}</div></div>""" if pin_b64 else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0;animation:zoomIn {dur:.2f}s cubic-bezier(0.25,0.1,0.25,1) forwards}}
@keyframes zoomIn{{from{{transform:scale(1)}}to{{transform:scale(1.12)}}}}
{CLOUDS_CSS}
.country-path{{fill:url(#countryGrad);stroke:#fff;stroke-width:3;filter:url(#glow);animation:pulseGlow 3s ease-in-out infinite}}
@keyframes pulseGlow{{0%,100%{{filter:url(#glow)}}50%{{filter:url(#glowBright)}}}}
.outlines{{fill:none;stroke:#fff;stroke-width:1.2;opacity:0.35}}
#overlay-text{{position:absolute;top:35%;left:0;width:100%;text-align:center;color:#fff;font-weight:900;font-size:60px;letter-spacing:2px;text-transform:uppercase;text-shadow:0 4px 30px rgba(0,0,0,0.95), 0 0 60px {c['glow2']};padding:0 60px;line-height:1.25;animation:textFade 1.2s ease-out forwards;opacity:0}}
@keyframes textFade{{0%{{opacity:0;transform:translateY(30px)}}40%{{opacity:0}}100%{{opacity:1;transform:translateY(0)}}}}
#pinwrap{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:600px;height:600px;animation:pinPop 0.7s 0.6s ease-out forwards;opacity:0}}
@keyframes pinPop{{from{{opacity:0;transform:translate(-50%,-50%) scale(0.5)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
#arcs{{position:absolute;inset:0}}
#pinring{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:190px;height:190px;border-radius:50%;border:5px solid #fff;overflow:hidden;box-shadow:0 0 50px {c['glow2']};background:#111}}
#pinring img{{width:100%;height:100%;object-fit:cover}}
#pinlabel{{position:absolute;left:50%;top:63%;transform:translateX(-50%);background:#fff;color:#8b0000;font-weight:900;font-size:34px;letter-spacing:2px;padding:8px 26px;border-radius:8px}}
</style></head><body>
<div id="wrap">
  {_bg_layer(sat)}
  {CLOUDS_HTML}
  <svg style="position:absolute;inset:0" width="1080" height="1920" viewBox="0 0 1080 1920">
    {_map_defs(c)}
    <path class="outlines" d="{outlines}"/>
    <path class="country-path" d="{path_d}"/>
  </svg>
  {pin_html}
</div>
<div id="overlay-text">{_html.escape(overlay_text or "INDIA NEWS")}</div>
</body></html>"""

# ---------------- SCENE: news frame (roundup + deep) ----------------
def news_frame_html(number, headline, photo_b64, location, dur, theme="purple",
                    style="deep", state=None, video_b64="", video_mime="video/mp4"):
    colors = {"purple": {"glow": "#c026d3", "glow2": "#7c3aed", "numColor": "#e879f9", "state": "#7c3aed"},
              "red": {"glow": "#dc2626", "glow2": "#991b1b", "numColor": "#f87171", "state": "#ff4d00"},
              "blue": {"glow": "#2563eb", "glow2": "#1e40af", "numColor": "#60a5fa", "state": "#2563eb"},
              "orange": {"glow": "#f59e0b", "glow2": "#b45309", "numColor": "#fbbf24", "state": "#ff8c00"},
              "green": {"glow": "#16a34a", "glow2": "#166534", "numColor": "#4ade80", "state": "#22c55e"},
              "olive": {"glow": "#a3a314", "glow2": "#6b6b0d", "numColor": "#d4d416", "state": "#b8b800"}}
    c = colors.get(theme, colors["purple"])
    safe_headline = _html.escape(headline or "HEADLINE")
    safe_location = _html.escape(location or "INDIA")

    if style == "roundup":
        sat = get_satellite_b64()
        outlines = _states_outline()
        state_d = get_state_path(state) if state else None
        cx, cy = get_state_centroid(state) if state else (540.0, 930.0)
        cy = min(max(cy, 500), 1450)
        frame_bottom = cy < 900
        anchor_y = 1105 if frame_bottom else 705
        conn = f'<path d="M{cx:.0f} {cy:.0f} C {cx-80:.0f} {(cy+anchor_y)/2:.0f}, 620 {(cy+anchor_y)/2:.0f}, 540 {anchor_y}" stroke="#d4e300" stroke-width="7" fill="none" stroke-linecap="round" filter="url(#softGlow)"/>'
        circ = f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="55" fill="#fff" filter="url(#softGlow)"/><text x="{cx:.0f}" y="{cy:.0f}" dy="0.35em" text-anchor="middle" font-family="Arial Black" font-size="58" font-weight="900" fill="#b33000">{number}</text>'
        if video_b64:
            media_html = f'<video src="data:{video_mime};base64,{video_b64}" autoplay muted loop playsinline></video>'
        elif photo_b64:
            media_html = f'<img src="data:image/jpeg;base64,{photo_b64}" alt=""/>'
        else:
            media_html = '<div class="no-photo"></div>'
        frame_top = "1080px" if frame_bottom else "90px"
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#frame-wrap{{position:absolute;top:{frame_top};left:50%;transform:translateX(-50%);width:940px;z-index:20;animation:frameIn 0.5s ease-out forwards;opacity:0}}
@keyframes frameIn{{from{{opacity:0;transform:translateX(-50%) translateY(-30px) scale(0.96)}}to{{opacity:1;transform:translateX(-50%) translateY(0) scale(1)}}}}
#photo-frame{{width:940px;height:500px;border:4px dashed #d4e300;border-radius:6px;overflow:hidden;box-shadow:0 0 40px rgba(212,227,0,0.25)}}
#photo-frame img,#photo-frame video,.no-photo{{width:100%;height:100%;object-fit:cover}}
.no-photo{{background:radial-gradient(circle at 50% 40%, #202020 0%, #0a0a0a 85%)}}
#headline-box{{position:relative;margin:-70px 50px 0;background:#f8f8f8;border-radius:4px;padding:20px 28px;box-shadow:0 10px 40px rgba(0,0,0,0.7)}}
#headline-box h2{{color:#111;font-family:Georgia,'Times New Roman',serif;font-size:34px;font-weight:800;line-height:1.35}}
</style></head><body>
{_bg_layer(sat, bright=0.55)}
<svg style="position:absolute;inset:0" width="1080" height="1920" viewBox="0 0 1080 1920">
  {_map_defs(c)}
  <path d="{outlines}" fill="none" stroke="#fff" stroke-width="1.5" opacity="0.55"/>
  {f'<path d="{state_d}" fill="{c["state"]}" opacity="0.85" stroke="#fff" stroke-width="2" filter="url(#softGlow)"/>' if state_d else ''}
  {conn}{circ}
</svg>
<div id="frame-wrap"><div id="photo-frame">{media_html}</div>
<div id="headline-box"><h2>{safe_headline}</h2></div></div>
</body></html>"""

    # deep style
    path_d, _, _ = get_country_path("India") or (_india_fallback_path(), 0, 0)
    photo_html = f'<img src="data:image/jpeg;base64,{photo_b64}" alt=""/>' if photo_b64 else '<div class="no-photo"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#frame-wrap{{position:absolute;top:80px;left:50%;transform:translateX(-50%);width:920px;animation:frameIn 0.5s ease-out forwards;opacity:0}}
@keyframes frameIn{{from{{opacity:0;transform:translateX(-50%) translateY(-40px) scale(0.95)}}to{{opacity:1;transform:translateX(-50%) translateY(0) scale(1)}}}}
#photo-frame{{width:920px;height:520px;border:3px dashed #ffeb3b;border-radius:8px;overflow:hidden;box-shadow:0 0 30px rgba(255,235,59,0.15)}}
#photo-frame img,.no-photo{{width:100%;height:100%;object-fit:cover}}
.no-photo{{background:radial-gradient(circle at 50% 40%, #202020 0%, #0a0a0a 85%)}}
#connector{{position:absolute;top:600px;left:50%;width:4px;height:120px;background:linear-gradient(to bottom, #ffeb3b, transparent);transform:translateX(-50%) scaleY(0);transform-origin:top;animation:lineGrow 0.4s 0.3s ease-out forwards}}
@keyframes lineGrow{{to{{transform:translateX(-50%) scaleY(1)}}}}
#num-circle{{position:absolute;top:700px;left:50%;transform:translateX(-50%);width:100px;height:100px;border-radius:50%;background:linear-gradient(135deg, {c['numColor']}, {c['glow']});display:flex;align-items:center;justify-content:center;box-shadow:0 0 40px {c['glow']};animation:circlePop 0.5s 0.5s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0;z-index:10}}
@keyframes circlePop{{from{{opacity:0;transform:translateX(-50%) scale(0)}}to{{opacity:1;transform:translateX(-50%) scale(1)}}}}
#num-circle span{{color:#fff;font-size:52px;font-weight:900;font-family:Arial Black}}
#headline-box{{position:absolute;top:840px;left:50%;transform:translateX(-50%);width:900px;background:rgba(0,0,0,0.75);border:1px solid rgba(255,255,255,0.15);border-radius:12px;padding:30px 40px;animation:textIn 0.6s 0.7s ease-out forwards;opacity:0}}
@keyframes textIn{{from{{opacity:0;transform:translateX(-50%) translateY(20px)}}to{{opacity:1;transform:translateX(-50%) translateY(0)}}}}
#headline-box h2{{color:#fff;font-size:42px;font-weight:800;line-height:1.3;text-transform:uppercase}}
#location-tag{{display:inline-block;margin-top:16px;background:{c['glow']};color:#fff;font-size:22px;font-weight:700;padding:6px 18px;border-radius:6px;letter-spacing:1px}}
.outlines{{fill:none;stroke:#fff;stroke-width:1;opacity:0.55}}
</style></head><body>
<svg style="position:absolute;inset:0" width="1080" height="1920" viewBox="0 0 1080 1920">
  {_map_defs(c)}
  <path class="outlines" d="{_states_outline()}"/>
  <path d="{path_d}" fill="none" stroke="#fff" stroke-width="1.5" opacity="0.3"/>
</svg>
<div id="frame-wrap"><div id="photo-frame">{photo_html}</div></div>
<div id="connector"></div>
<div id="num-circle"><span>{number}</span></div>
<div id="headline-box"><h2>{safe_headline}</h2><div id="location-tag">{safe_location}</div></div>
</body></html>"""

# ---------------- SCENE: article card (black highlight) ----------------
def article_card_html(masthead, headline, category, date_str, bg_b64, dur, source_color="#111"):
    safe_masthead = _html.escape(masthead or "NEWS SOURCE").upper()
    safe_headline = _html.escape(headline or "HEADLINE")
    safe_category = _html.escape(category or "NEWS").upper()
    safe_date = _html.escape(date_str or _date_str())
    words = safe_headline.split()
    k = min(len(words), max(4, int(len(words) * 0.5)))
    hl = " ".join(words[:k]); rest = " ".join(words[k:])
    bg_html = f'<img id="bg" src="data:image/jpeg;base64,{bg_b64}" alt=""/>' if bg_b64 else '<div id="bg" style="background:#888"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#bg{{position:absolute;inset:-80px;width:1240px;height:2080px;object-fit:cover;filter:blur(24px) brightness(0.55) grayscale(0.6);animation:kb {dur:.2f}s linear forwards}}
@keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.08)}}}}
#card{{position:absolute;top:50%;left:50%;width:920px;transform:translate(-50%,-50%);background:#f4f4f4;box-shadow:0 40px 100px rgba(0,0,0,0.9);animation:cardIn 0.5s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes cardIn{{from{{opacity:0;transform:translate(-50%,-50%) scale(0.92)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
#masthead{{padding:28px 40px 16px;display:flex;align-items:center;gap:20px;border-bottom:1px solid #ddd}}
#masthead .bars{{color:#333;font-size:30px}}
#masthead h1{{font-family:Georgia,serif;font-size:38px;font-weight:800;color:#111}}
#nav{{padding:12px 40px;color:#555;font-size:20px;border-bottom:1px solid #eee}}
#nav span{{margin-right:26px}}
#headline{{padding:28px 40px 10px;font-size:44px;font-weight:700;line-height:1.5;color:#111}}
#headline .hl{{background:{source_color};color:#fff;padding:2px 8px;box-decoration-break:clone;-webkit-box-decoration-break:clone}}
#meta{{padding:0 40px 28px;color:#777;font-size:20px}}
#meta .tag{{border:1.5px solid #999;border-radius:999px;padding:4px 16px;color:#444;margin-right:12px}}
</style></head><body>
{bg_html}
<div id="card">
  <div id="masthead"><span class="bars">&#9776;</span><h1>{safe_masthead}</h1></div>
  <div id="nav"><span>News</span><span>Videos</span><span>India</span><span>World</span><span>City</span></div>
  <div id="headline">{rest} <span class="hl">{hl}</span></div>
  <div id="meta"><span class="tag">{safe_category}</span> | TNN | {safe_date}</div>
</div>
</body></html>"""

# ---------------- SCENE: keyword text over footage ----------------
def keyword_text_html(keyword, footage_b64, dur):
    safe = _html.escape(keyword or "NEWS").upper()
    bg = f'<img id="bg" src="data:image/jpeg;base64,{footage_b64}" alt=""/>' if footage_b64 else '<div id="bg" style="background:#111"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial Black,Arial,sans-serif}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(0.6) contrast(1.1);animation:kb {dur:.2f}s linear forwards}}
@keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.1)}}}}
#txt{{position:absolute;top:50%;left:0;width:100%;transform:translateY(-50%);text-align:center;color:#fff;font-size:110px;font-weight:900;letter-spacing:4px;text-shadow:0 4px 20px rgba(0,0,0,0.9), 0 0 60px rgba(0,0,0,0.6);animation:pop 0.6s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes pop{{from{{opacity:0;transform:translateY(-50%) scale(0.6)}}to{{opacity:1;transform:translateY(-50%) scale(1)}}}}
</style></head><body>{bg}<div id="txt">{safe}</div></body></html>"""

# ---------------- SCENE: stat callout with red annotations ----------------
def stat_callout_html(stat_text, label, bg_b64, dur, theme="purple", extra_lines=None, photo_b64=""):
    safe_stat = _html.escape(stat_text or "0")
    safe_label = _html.escape(label or "")
    extras = "".join(f'<div class="xline">{_html.escape(x)}</div>' for x in (extra_lines or []))
    bg = f'<img id="bg" src="data:image/jpeg;base64,{bg_b64}" alt=""/>' if bg_b64 else '<div id="bg" style="background:#0a0a0a"></div>'
    mini = f'<div id="mini"><img src="data:image/jpeg;base64,{photo_b64}"/></div>' if photo_b64 else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(0.35)}}
#wrap{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:30px}}
#main{{position:relative;color:#fff;font-size:72px;font-weight:900;text-align:center;line-height:1.25;padding:20px 40px;animation:in1 0.6s ease-out forwards;opacity:0}}
@keyframes in1{{from{{opacity:0;transform:scale(0.8)}}to{{opacity:1;transform:scale(1)}}}}
#scribble{{position:absolute;inset:-20px -40px;pointer-events:none}}
#scribble ellipse{{fill:none;stroke:#e00000;stroke-width:7;transform:rotate(-6deg);transform-origin:center;animation:draw 0.8s 0.5s ease-out forwards;stroke-dasharray:2200;stroke-dashoffset:2200}}
@keyframes draw{{to{{stroke-dashoffset:0}}}}
.xline{{color:#eee;font-size:44px;font-weight:800;text-align:center;animation:in1 0.6s ease-out forwards;opacity:0}}
#note{{position:absolute;top:16%;right:8%;transform:rotate(8deg);color:#fff;font-size:34px;font-weight:700;text-shadow:0 2px 10px #000;animation:in1 0.6s 1s ease-out forwards;opacity:0}}
#arrow{{position:absolute;top:24%;left:38%;width:300px;height:300px;animation:in1 0.6s 0.9s ease-out forwards;opacity:0}}
#arrow path{{fill:none;stroke:#e00000;stroke-width:8;stroke-linecap:round}}
#mini{{position:absolute;bottom:10%;left:50%;transform:translateX(-50%);width:220px;height:220px;border-radius:50%;border:5px solid #b00;overflow:hidden;box-shadow:0 0 40px rgba(200,0,0,0.5)}}
#mini img{{width:100%;height:100%;object-fit:cover}}
#lbl{{position:absolute;bottom:6%;left:50%;transform:translateX(-50%);background:#fff;color:#8b0000;font-weight:900;font-size:34px;letter-spacing:2px;padding:8px 30px;border-radius:8px}}
</style></head><body>
{bg}
<div id="wrap">
  <div id="main">{safe_stat}
    <svg id="scribble" viewBox="0 0 600 220" preserveAspectRatio="none"><ellipse cx="300" cy="110" rx="280" ry="95"/></svg>
  </div>
  {extras}
</div>
<svg id="arrow" viewBox="0 0 300 300"><path d="M20 280 C 120 200, 60 120, 180 60 M180 60 l-40 10 M180 60 l-5 42"/></svg>
<div id="note">{safe_label}</div>
{mini}
{f'<div id="lbl">{safe_label}</div>' if photo_b64 else ''}
</body></html>"""

# ---------------- SCENE: table card ----------------
def table_card_html(table_title, rows, dur):
    title = _html.escape(table_title or "DATA")
    trs = "".join(f'<tr><td>{_html.escape(r[0])}</td><td><span class="hl">{_html.escape(r[1])}</span></td></tr>'
                  for r in (rows or []))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#777;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#card{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:880px;background:#f6f6f6;box-shadow:0 40px 100px rgba(0,0,0,0.8);animation:cardIn 0.5s ease-out forwards;opacity:0}}
@keyframes cardIn{{from{{opacity:0;transform:translate(-50%,-50%) scale(0.92)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
h1{{padding:30px 40px 10px;font-size:40px;color:#111}}
table{{width:100%;border-collapse:collapse;font-size:32px}}
td{{border:1px solid #ccc;padding:20px 30px;color:#333}}
td:first-child{{color:#555}}
.hl{{background:#111;color:#fff;padding:4px 12px}}
</style></head><body>
<div id="card"><h1>{title}</h1><table>{trs}</table></div>
</body></html>"""

# ---------------- SCENE: location highlight ----------------
def location_highlight_html(country, location, photo_b64, overlay_text, dur, theme="red"):
    colors = {"red": {"glow": "#dc2626", "glow2": "#991b1b"}, "purple": {"glow": "#c026d3", "glow2": "#7c3aed"}, "blue": {"glow": "#2563eb", "glow2": "#1e40af"}}
    c = colors.get(theme, colors["red"])
    path_d, _, _ = get_country_path(country or "India") or (_india_fallback_path(), 0, 0)
    safe_text = _html.escape(overlay_text or location or "LOCATION")
    safe_loc = _html.escape(location or "LOCATION")
    photo_html = f'<div id="photo-wrap"><img src="data:image/jpeg;base64,{photo_b64}" alt=""/></div>' if photo_b64 else ""
    label_top = "62%" if photo_b64 else "45%"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#wrap{{position:absolute;inset:0;animation:zoomIn {dur:.2f}s ease-out forwards}}
@keyframes zoomIn{{from{{transform:scale(1.3)}}to{{transform:scale(1)}}}}
.country{{fill:url(#locGrad);stroke:#fff;stroke-width:2.5;filter:url(#locGlow);animation:pulseLoc 2.5s ease-in-out infinite}}
@keyframes pulseLoc{{0%,100%{{opacity:0.9}}50%{{opacity:1}}}}
#photo-wrap{{position:absolute;top:28%;left:50%;transform:translateX(-50%);width:700px;height:500px;animation:photoIn 0.6s 0.3s ease-out forwards;opacity:0;z-index:20}}
@keyframes photoIn{{from{{opacity:0;transform:translateX(-50%) scale(0.85)}}to{{opacity:1;transform:translateX(-50%) scale(1)}}}}
#photo-wrap img{{width:100%;height:100%;object-fit:cover;border:3px solid rgba(255,255,255,0.3)}}
#loc-label{{position:absolute;top:{label_top};left:50%;transform:translateX(-50%);background:{c['glow']};color:#fff;font-weight:900;font-size:42px;padding:12px 32px;border-radius:8px;letter-spacing:2px;text-transform:uppercase;box-shadow:0 0 40px {c['glow']};animation:labelIn 0.5s 0.6s ease-out forwards;opacity:0;z-index:20}}
@keyframes labelIn{{from{{opacity:0;transform:translateX(-50%) translateY(20px)}}to{{opacity:1;transform:translateX(-50%) translateY(0)}}}}
#overlay-text{{position:absolute;bottom:180px;left:0;width:100%;text-align:center;color:#fff;font-weight:800;font-size:48px;padding:0 80px;line-height:1.3;text-shadow:0 4px 20px rgba(0,0,0,0.9);animation:textIn 0.6s 0.8s ease-out forwards;opacity:0}}
@keyframes textIn{{from{{opacity:0;transform:translateY(30px)}}to{{opacity:1;transform:translateY(0)}}}}
</style></head><body>
<div id="wrap">
  {_bg_layer(get_satellite_b64(), bright=0.35)}
  <svg style="position:absolute;inset:0" width="1080" height="1920" viewBox="0 0 1080 1920">
    <defs><linearGradient id="locGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="{c['glow']}"/><stop offset="100%" stop-color="{c['glow2']}"/></linearGradient>
    <filter id="locGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="8" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <path class="country" d="{path_d}"/>
  </svg>
  {photo_html}
  <div id="loc-label">{safe_loc}</div>
  <div id="overlay-text">{safe_text}</div>
</div>
</body></html>"""

# ---------------- SCENE: disaster dramatic ----------------
def disaster_dramatic_html(headline, sub_text, footage_b64, dur):
    safe_headline = _html.escape(headline or "BREAKING").upper()
    safe_sub = _html.escape(sub_text or "")
    bg = f'<img id="bg" src="data:image/jpeg;base64,{footage_b64}" alt=""/>' if footage_b64 else '<div id="bg" style="background:#160404"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(0.4) contrast(1.2)}}
#red-overlay{{position:absolute;inset:0;background:linear-gradient(180deg, rgba(180,0,0,0.5), rgba(80,0,0,0.8));mix-blend-mode:multiply;animation:redPulse 3s infinite}}
@keyframes redPulse{{0%,100%{{opacity:0.85}}50%{{opacity:1}}}}
#alert-bar{{position:absolute;top:0;width:100%;height:8px;background:linear-gradient(90deg,#f00,#f44,#f00);animation:flash 1s infinite}}
@keyframes flash{{0%,100%{{opacity:1}}50%{{opacity:0.6}}}}
#hw{{position:absolute;top:50%;left:0;width:100%;transform:translateY(-50%);text-align:center;padding:0 60px;animation:tIn 0.7s ease-out forwards;opacity:0}}
@keyframes tIn{{from{{opacity:0;transform:translateY(-50%) scale(0.9)}}to{{opacity:1;transform:translateY(-50%) scale(1)}}}}
h1{{color:#fff;font-size:72px;font-weight:900;line-height:1.15;text-transform:uppercase;letter-spacing:2px;text-shadow:0 4px 30px #000, 0 0 60px rgba(255,0,0,0.5);margin-bottom:20px}}
.sub{{color:#faa;font-size:36px;font-weight:700;line-height:1.4}}
#badge{{position:absolute;bottom:120px;left:0;width:100%;text-align:center}}
#badge span{{display:inline-block;background:#f00;color:#fff;font-size:24px;font-weight:900;padding:8px 24px;border-radius:4px;letter-spacing:2px;box-shadow:0 0 30px rgba(255,0,0,0.6)}}
</style></head><body>{bg}<div id="red-overlay"></div><div id="alert-bar"></div>
<div id="hw"><h1>{safe_headline}</h1><div class="sub">{safe_sub}</div></div>
<div id="badge"><span>BREAKING NEWS</span></div></body></html>"""

# ---------------- SCENE: footage highlight ----------------
def footage_highlight_html(footage_b64, circle_x=540, circle_y=960, circle_r=200, label_text="", dur=5):
    safe_label = _html.escape(label_text or "")
    bg = f'<img id="bg" src="data:image/jpeg;base64,{footage_b64}" alt=""/>' if footage_b64 else '<div id="bg" style="background:#111"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
#highlight circle{{fill:none;stroke:#f00;stroke-width:6;stroke-dasharray:20 10;animation:spin 8s linear infinite}}
@keyframes spin{{to{{stroke-dashoffset:-300}}}}
#label{{position:absolute;left:50%;top:{circle_y+circle_r+60}px;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#f44;font-size:28px;font-weight:800;padding:10px 24px;border-radius:6px;border:2px solid #f44;white-space:nowrap}}
</style></head><body>{bg}
<svg width="1080" height="1920" style="position:absolute;inset:0">
<defs><mask id="m"><rect width="1080" height="1920" fill="white"/><circle cx="{circle_x}" cy="{circle_y}" r="{circle_r}" fill="black"/></mask></defs>
<rect width="1080" height="1920" fill="rgba(0,0,0,0.35)" mask="url(#m)"/></svg>
<div id="highlight" style="position:absolute;left:{circle_x-circle_r}px;top:{circle_y-circle_r}px;width:{circle_r*2}px;height:{circle_r*2}px">
<svg viewBox="0 0 {circle_r*2} {circle_r*2}"><circle cx="{circle_r}" cy="{circle_r}" r="{circle_r-5}"/></svg></div>
{f'<div id="label">{safe_label}</div>' if safe_label else ''}
</body></html>"""

# ---------------- SCENE: breaking card ----------------
def breaking_card_html(headline, sub, img_b64, dur, source=""):
    safe_headline = _html.escape(headline or "BREAKING NEWS").upper()
    safe_sub = _html.escape(sub or "")
    safe_source = _html.escape(source or "")
    words = safe_headline.split(); k = min(4, len(words))
    hl_words = " ".join(words[:k]); rest_words = " ".join(words[k:])
    img_html = f'<img src="data:image/jpeg;base64,{img_b64}" alt=""/>' if img_b64 else '<div style="width:100%;height:100%;background:linear-gradient(135deg,#222,#0a0a0a)"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#111;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
.accent-line{{position:absolute;height:3px;background:linear-gradient(90deg, transparent, #f00, transparent);animation:lp 2s infinite}}
.al1{{top:200px;width:100%}}.al2{{bottom:200px;width:100%}}
@keyframes lp{{0%,100%{{opacity:0.3}}50%{{opacity:0.8}}}}
#card{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:950px;background:#fff;box-shadow:0 50px 100px rgba(0,0,0,0.9);animation:cardIn 0.5s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes cardIn{{from{{opacity:0;transform:translate(-50%,-50%) scale(0.9) rotate(-2deg)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
#breaking{{padding:35px 45px 15px;font-size:130px;font-weight:900;letter-spacing:-3px;color:#000;line-height:0.9;animation:bIn 0.4s 0.2s ease-out forwards;opacity:0}}
@keyframes bIn{{from{{opacity:0;transform:translateX(-30px)}}to{{opacity:1;transform:translateX(0)}}}}
#hl{{padding:0 45px 20px;font-size:54px;font-weight:800;line-height:1.2;color:#000}}
#hl .red{{background:#d40000;color:#fff;padding:2px 10px;margin-right:4px}}
#sub{{padding:0 45px 25px;font-size:28px;color:#444;font-weight:600}}
#img-wrap{{width:100%;height:720px;overflow:hidden;position:relative}}
#img-wrap img{{width:100%;height:100%;object-fit:cover}}
#source-badge{{position:absolute;bottom:40px;left:45px;background:#c00;color:#fff;font-weight:900;font-size:32px;padding:10px 24px;letter-spacing:1px}}
#date-badge{{position:absolute;bottom:40px;right:45px;background:#111;color:#fff;font-weight:800;font-size:26px;padding:10px 20px}}
</style></head><body>
<div class="accent-line al1"></div><div class="accent-line al2"></div>
<div id="card"><div id="breaking">BREAKING</div>
<div id="hl"><span class="red">{hl_words}</span> {rest_words}</div>
<div id="sub">{safe_sub}</div>
<div id="img-wrap">{img_html}<div id="source-badge">{safe_source or "LIVE UPDATE"}</div><div id="date-badge">{_date_str()}</div></div></div>
</body></html>"""

# ---------------- SCENE: quote card ----------------
def quote_card_html(quote_text, person, dur, theme="purple"):
    colors = {"purple": {"accent": "#c026d3", "bg": "#0a0a0a"}, "red": {"accent": "#dc2626", "bg": "#0a0505"}, "blue": {"accent": "#2563eb", "bg": "#050a0a"}}
    c = colors.get(theme, colors["purple"])
    safe_quote = _html.escape(quote_text or "")
    safe_person = _html.escape(person or "Official Statement")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:{c['bg']};overflow:hidden;font-family:Georgia,serif}}
#wrap{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:80px}}
#qmark{{position:absolute;top:120px;left:60px;font-size:280px;color:{c['accent']};opacity:0.15;line-height:1}}
#card{{width:100%;background:linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.03));border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:60px;animation:cardIn 0.5s ease-out forwards;opacity:0}}
@keyframes cardIn{{from{{opacity:0;transform:translateY(30px)}}to{{opacity:1;transform:translateY(0)}}}}
#quote{{font-size:44px;line-height:1.5;color:#f0f0f0;font-style:italic}}
#person{{margin-top:40px;padding-top:30px;border-top:2px solid {c['accent']};display:flex;align-items:center;gap:20px}}
#pav{{width:70px;height:70px;border-radius:50%;background:linear-gradient(135deg, {c['accent']}, #333);display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px;font-weight:900;font-family:Arial}}
#pname{{color:#fff;font-size:32px;font-weight:700;font-family:Arial}}
</style></head><body><div id="wrap"><div id="qmark">"</div>
<div id="card"><div id="quote">"{safe_quote}"</div>
<div id="person"><div id="pav">{safe_person[0] if safe_person else "?"}</div><div id="pname">{safe_person}</div></div></div></div></body></html>"""

# ---------------- SCENE: stat overlay (legacy) ----------------
def stat_overlay_html(stat_text, label, bg_b64, dur, theme="purple"):
    colors = {"purple": {"glow": "#c026d3", "accent": "#e879f9"}, "red": {"glow": "#dc2626", "accent": "#f87171"},
              "blue": {"glow": "#2563eb", "accent": "#60a5fa"}, "gold": {"glow": "#f59e0b", "accent": "#fbbf24"}}
    c = colors.get(theme, colors["purple"])
    bg = f'<img id="bg" src="data:image/jpeg;base64,{bg_b64}" alt=""/>' if bg_b64 else '<div id="bg" style="background:#0a0a0a"></div>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#bg{{position:absolute;inset:-60px;width:1200px;height:2040px;object-fit:cover;filter:blur(15px) brightness(0.25);animation:kb {dur:.2f}s linear forwards}}
@keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.1)}}}}
#sw{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;animation:sIn 0.7s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes sIn{{from{{opacity:0;transform:translate(-50%,-50%) scale(0.5)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
#sc{{width:520px;height:520px;border-radius:50%;background:rgba(0,0,0,0.7);border:4px solid {c['glow']};display:flex;flex-direction:column;align-items:center;justify-content:center;box-shadow:0 0 80px {c['glow']}40;animation:cp 3s infinite}}
@keyframes cp{{0%,100%{{box-shadow:0 0 80px {c['glow']}40}}50%{{box-shadow:0 0 140px {c['glow']}70}}}}
#sn{{color:#fff;font-size:110px;font-weight:900;font-family:Arial Black;line-height:1}}
#sl{{color:{c['accent']};font-size:34px;font-weight:800;margin-top:16px;letter-spacing:3px;text-transform:uppercase}}
</style></head><body>{bg}<div id="sw"><div id="sc"><div id="sn">{_html.escape(stat_text or "0")}</div><div id="sl">{_html.escape(label or "")}</div></div></div></body></html>"""

def stat_callout_html(stat_text, label, bg_b64, dur, theme="purple", extra_lines=None, photo_b64=""):
    safe_stat = _html.escape(stat_text or "0")
    safe_label = _html.escape(label or "")
    extras = "".join(f'<div class="xline">{_html.escape(x)}</div>' for x in (extra_lines or []))
    bg = f'<img id="bg" src="data:image/jpeg;base64,{bg_b64}" alt=""/>' if bg_b64 else '<div id="bg" style="background:#0a0a0a"></div>'
    mini = f'<div id="mini"><img src="data:image/jpeg;base64,{photo_b64}"/></div>' if photo_b64 else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#bg{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:brightness(0.35) grayscale(0.5)}}
#wrap{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:30px}}
#main{{position:relative;color:#fff;font-size:84px;font-weight:900;text-align:center;line-height:1.2;padding:20px 40px;animation:in1 0.6s ease-out forwards;opacity:0}}
@keyframes in1{{from{{opacity:0;transform:scale(0.8)}}to{{opacity:1;transform:scale(1)}}}}
#scribble{{position:absolute;inset:-20px -40px;pointer-events:none}}
#scribble ellipse{{fill:none;stroke:#e00000;stroke-width:8;transform:rotate(-4deg);transform-origin:center;animation:draw 0.8s 0.5s ease-out forwards;stroke-dasharray:2200;stroke-dashoffset:2200}}
@keyframes draw{{to{{stroke-dashoffset:0}}}}
.xline{{color:#eee;font-size:40px;font-weight:800;text-align:center;animation:in1 0.6s ease-out forwards;opacity:0}}
#note{{position:absolute;top:18%;right:10%;transform:rotate(6deg);color:#fff;font-size:32px;font-weight:700;text-shadow:0 2px 10px #000;animation:in1 0.6s 1s ease-out forwards;opacity:0}}
#arrow{{position:absolute;top:26%;left:40%;width:250px;height:250px;animation:in1 0.6s 0.9s ease-out forwards;opacity:0}}
#arrow path{{fill:none;stroke:#e00000;stroke-width:8;stroke-linecap:round}}
#mini{{position:absolute;bottom:12%;left:50%;transform:translateX(-50%);width:200px;height:200px;border-radius:50%;border:6px solid #b00;overflow:hidden;box-shadow:0 0 40px rgba(200,0,0,0.5)}}
#mini img{{width:100%;height:100%;object-fit:cover}}
#lbl{{position:absolute;bottom:7%;left:50%;transform:translateX(-50%);background:#fff;color:#8b0000;font-weight:900;font-size:32px;letter-spacing:2px;padding:8px 30px;border-radius:8px}}
</style></head><body>
{bg}
<div id="wrap">
  <div id="main">{safe_stat}
    <svg id="scribble" viewBox="0 0 600 220" preserveAspectRatio="none"><ellipse cx="300" cy="110" rx="280" ry="95"/></svg>
  </div>
  {extras}
</div>
<svg id="arrow" viewBox="0 0 300 300"><path d="M20 280 C 120 200, 60 120, 180 60 M180 60 l-40 10 M180 60 l-5 42"/></svg>
<div id="note">{safe_label}</div>
{mini}
{f'<div id="lbl">{safe_label}</div>' if photo_b64 else ''}
</body></html>"""

# ---------------- SCENE: outro (white IG card, no logo) ----------------
def outro_html(dur=4):
    sat = get_satellite_b64()
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;background:#111;overflow:hidden;font-family:Arial,Helvetica,sans-serif}}
#card{{position:absolute;top:44%;left:50%;transform:translate(-50%,-50%);width:880px;background:#fff;border-radius:24px;padding:50px;box-shadow:0 40px 120px rgba(0,0,0,0.8);animation:cardIn 0.6s cubic-bezier(0.34,1.56,0.64,1) forwards;opacity:0}}
@keyframes cardIn{{from{{opacity:0;transform:translate(-50%,-50%) scale(0.9)}}to{{opacity:1;transform:translate(-50%,-50%) scale(1)}}}}
#row{{display:flex;align-items:center;gap:30px}}
#avatar{{width:140px;height:140px;border-radius:50%;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5);padding:5px}}
#avatar-inner{{width:100%;height:100%;border-radius:50%;background:#000;display:flex;align-items:center;justify-content:center}}
#avatar-inner svg{{width:90px;height:90px}}
#name{{font-size:44px;font-weight:800;color:#111;display:flex;align-items:center;gap:12px}}
#name svg{{width:36px;height:36px}}
#stats{{display:flex;gap:60px;margin:36px 0;color:#111}}
#stats b{{font-size:40px;display:block}}
#stats span{{font-size:26px;color:#888}}
#btns{{display:flex;gap:20px}}
#follow{{position:relative;flex:1;height:88px}}
#f1,#f2{{position:absolute;inset:0;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:32px}}
#f1{{background:#3897ef;color:#fff;animation:fl1 2s infinite}}
#f2{{background:#555;color:#fff;opacity:0;animation:fl2 2s infinite}}
@keyframes fl1{{0%,45%{{opacity:1}}55%,100%{{opacity:0}}}}
@keyframes fl2{{0%,45%{{opacity:0}}55%,100%{{opacity:1}}}}
#msg{{flex:1;background:#333;color:#fff;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:32px}}
#iglogo{{position:absolute;top:64%;left:50%;transform:translateX(-50%);margin-top:60px;text-align:center;animation:logoIn 1s 0.8s ease-out forwards;opacity:0}}
@keyframes logoIn{{from{{opacity:0;transform:translateX(-50%) scale(0.5)}}to{{opacity:1;transform:translateX(-50%) scale(1)}}}}
#iglogo svg{{width:110px;height:110px}}
#bigh{{margin-top:24px;color:#fff;font-size:38px;font-weight:800;letter-spacing:2px;text-shadow:0 2px 10px #000}}
</style></head><body>
{_bg_layer(sat, blur=0, bright=0.4)}
<div id="card">
  <div id="row"><div id="avatar"><div id="avatar-inner"><svg viewBox="0 0 44 46"><path d="{_mini_india_path()}" fill="#fff"/></svg></div></div>
  <div id="name">indiainlast24hr<svg viewBox="0 0 24 24" fill="#3897f0"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg></div></div>
  <div id="stats"><div><b>2546</b><span>posts</span></div><div><b>4.5M</b><span>followers</span></div><div><b>120</b><span>following</span></div></div>
  <div id="btns"><div id="follow"><div id="f1">Follow</div><div id="f2">Following &#9662;</div></div><div id="msg">Message</div></div>
</div>
<div id="iglogo"><svg viewBox="0 0 24 24" fill="none" stroke="url(#igGrad)" stroke-width="1.5">
<defs><linearGradient id="igGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="#feda75"/><stop offset="25%" stop-color="#fa7e1e"/><stop offset="50%" stop-color="#d62976"/><stop offset="75%" stop-color="#962fbf"/><stop offset="100%" stop-color="#4f5bd5"/></linearGradient></defs>
<rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>
<div id="bigh">@INDIAINLAST24HR</div></div>
</body></html>"""

def _mini_india_path():
    return "M" + "L".join(f"{(lo-66)*(44/34):.1f} {(38-la)*(46/34)+2:.1f}" for lo, la in _INDIA_FALLBACK) + "Z"

# ---------------- legacy wrappers ----------------
def map_html(country, pin, overlay_text, dur, lat=None, lon=None, topic_img=None):
    return map_intro_html(country, overlay_text, dur, theme="purple", topic_img=topic_img, pin=pin)

def shot_card_html(shot_path, bg_path, source, dur):
    return article_card_html(source, "BREAKING NEWS", "NEWS", _date_str(), bg_path, dur)

def breaking_html(headline, sub, img_path, dur):
    return breaking_card_html(headline, sub, _b64_or_empty(img_path), dur)

def quote_html(text, person, timings, dur):
    return quote_card_html(text, person, dur)

def outro_video():
    cache = Path(settings.output_dir) / "outro.mp4"
    if cache.exists():
        return str(cache)
    webm = record_html(outro_html(4), 4, "outro")
    import imageio_ffmpeg as ioff, subprocess
    subprocess.run([ioff.get_ffmpeg_exe(), "-y", "-i", webm, "-vf", "fps=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cache)], check=True, capture_output=True)
    return str(cache)