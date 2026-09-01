import html, os, datetime
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from .config import settings

RAW = Path(settings.output_dir).resolve() / "raw"

# Reposition handle to bottom-right so it never overlaps content
HANDLE_FIX_CSS = "#handle{top:auto!important;bottom:70px!important;right:44px!important}"

def record_html(page_html, dur, name):
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}.html"; p.write_text(page_html, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1080, "height": 1920},
                            record_video_dir=str(RAW), record_video_size={"width": 1080, "height": 1920})
        pg = ctx.new_page()
        pg.goto(p.resolve().as_uri())
        pg.add_style_tag(content=HANDLE_FIX_CSS)       # P6.3: handle never overlaps
        pg.wait_for_timeout(int(dur * 1000))
        v = pg.video; pg.close(); out = v.path(); ctx.close(); b.close()
    return out

def spans(text, timings, step=0.3):
    words = text.split(); out = []
    for i, w in enumerate(words):
        d = timings[i][1] + step if i < len(timings) else step + i * 0.35
        out.append(f'<span class="w"><i style="animation-delay:{d:.2f}s"></i><b>{html.escape(w)}</b></span>')
    return " ".join(out)

# Continuous highlight (closes gaps between words)
KARAOKE_CSS = """.w{position:relative;display:inline-block;margin-right:0.25ch}
.w i{position:absolute;left:-2px;right:-0.35ch;top:6%;height:88%;background:#d40000;opacity:.95;transform:scaleX(0);transform-origin:left;animation:hl .16s forwards}
.w b{position:relative;font-weight:inherit}@keyframes hl{to{transform:scaleX(1)}}"""

def _geojson():
    if not hasattr(_geojson, "cache"):
        url = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
        _geojson.cache = httpx.get(url, timeout=60).json()
    return _geojson.cache

def map_html(country, pin, overlay_text, dur, lat=None, lon=None):
    gj = _geojson()["features"]
    name = lambda f: (f["properties"].get("NAME") or "").lower()
    target = next((f for f in gj if name(f) == country.lower()), None)
    if target is None: target = next((f for f in gj if country.lower() in name(f)), gj[0])
    
    def rings(f):
        g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        return [p[0] for p in polys]
        
    allr = [r for f in gj for r in rings(f)]
    xs = [c[0] for r in allr for c in r[::3]]; ys = [c[1] for r in allr for c in r[::3]]
    tr = [r for r in rings(target)]
    txs = [c[0] for r in tr for c in r]; tys = [c[1] for r in tr for c in r]
    
    # P6.2: Center on exact city coordinates if available, else country center
    if lat is not None and lon is not None:
        cx, cy = lon, lat
    else:
        cx, cy = (min(txs)+max(txs))/2, (min(tys)+max(tys))/2 
        
    w = max(max(txs)-min(txs), 20); pad = w * 1.5
    X = lambda lon: (lon - xs[0]) * 6; Y = lambda lat: (ys[1] - lat) * 6
    vx, vy, vw, vh = X(cx-pad/2), Y(cy+pad/2), X(cx+pad/2)-X(cx-pad/2), Y(cy-pad/2)-Y(cy+pad/2)
    
    def path(f, cls):
        d = "".join("M" + "L".join(f"{X(c[0]):.0f} {Y(c[1]):.0f}" for c in r[::2]) + "Z" for r in rings(f))
        return f'<path class="{cls}" d="{d}"/>'
        
    land = "".join(path(f, "l") for f in gj if f is not target)
    tgt = path(target, "t")
    pin_html = f'<div id="pin"><div class="rip"></div><div class="rip r2"></div><div class="dot"></div><div class="lbl">{html.escape(pin or country)}</div></div>' if pin or overlay_text else ""
    
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial}}
#wrap{{position:absolute;inset:0;animation:zm {dur:.1f}s ease-in forwards;transform-origin:50% 50%}}
@keyframes zm{{from{{transform:scale(1)}}to{{transform:scale(2.1)}}}}
svg{{width:100%;height:100%}}.l{{fill:#161616;stroke:#242424;stroke-width:1}}.t{{fill:#b00;stroke:#f33;stroke-width:2;filter:drop-shadow(0 0 18px #f00)}}
#noise{{position:absolute;inset:0;opacity:.18;background:repeating-radial-gradient(circle at 30% 40%,#111 0 2px,#000 2px 5px)}}
#vig{{position:absolute;inset:0;background:radial-gradient(circle,transparent 40%,#000 95%)}}
#pin{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center}}
.dot{{width:18px;height:18px;background:#fff;border-radius:50%;margin:0 auto;box-shadow:0 0 20px #fff}}
.rip{{position:absolute;left:50%;top:50%;width:20px;height:20px;margin:-10px;border:3px solid #fff;border-radius:50%;animation:rp 1.6s infinite}}
.r2{{animation-delay:.8s}}@keyframes rp{{to{{transform:scale(6);opacity:0}}}}
.lbl{{margin-top:14px;background:#fff;color:#111;font-weight:700;font-size:34px;padding:8px 22px;border-radius:6px;display:inline-block}}
#ov{{position:absolute;top:30%;width:100%;text-align:center;color:#fff;font-weight:800;font-size:64px;letter-spacing:3px;text-shadow:0 4px 16px #000;text-transform:uppercase}}
#logo{{position:fixed;top:48px;left:48px;color:#fff;font-weight:900;font-size:40px}}#logo b{{color:#e11}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px;text-shadow:0 2px 8px #000}}
</style></head><body>
<div id="wrap"><svg viewBox="{vx:.0f} {vy:.0f} {vw:.0f} {vh:.0f}">{land}{tgt}</svg><div id="noise"></div></div>
<div id="vig"></div>{pin_html}
<div id="ov">{html.escape(overlay_text or "")}</div>
<div id="logo">INDIA<b>24</b></div><div id="handle">{settings.ig_handle}</div>
</body></html>"""

def quote_html(text, person, timings, dur):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Georgia,serif}}
#q{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:940px;background:#f5f5f5;padding:60px;font-size:44px;line-height:1.5;color:#141414;box-shadow:0 30px 80px rgba(0,0,0,.8)}}
#p{{margin-top:34px;font:700 40px Arial;color:#111}}{KARAOKE_CSS}
#logo{{position:fixed;top:48px;left:48px;color:#fff;font-weight:900;font-size:40px}}#logo b{{color:#e11}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px}}
</style></head><body><div id="q">{spans(text, timings)}<div id="p">— {html.escape(person)}</div></div>
<div id="logo">INDIA<b>24</b></div><div id="handle">{settings.ig_handle}</div></body></html>"""

def breaking_html(headline, sub, img_path, dur):
    import base64
    b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
    words = headline.split(); k = min(6, len(words))
    hl = " ".join(f'<span class="r">{html.escape(w)}</span>' for w in words[:k]) + " " + html.escape(" ".join(words[k:]))
    # P6.3: Dynamic date badge (today's real date, not hardcoded)
    ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    date_str = ist_now.strftime("%d %b").upper()
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#222;overflow:hidden;font-family:Arial}}
#card{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:950px;background:#fff;animation:pop .4s ease-out}}
@keyframes pop{{from{{opacity:0;transform:translate(-50%,-50%) scale(.9)}}}}
#bk{{font-size:150px;font-weight:900;letter-spacing:-4px;color:#000;padding:40px 50px 0}}
#hl{{padding:10px 50px;font-size:56px;font-weight:800;line-height:1.3;color:#000}}
.r{{background:#d40000;color:#000}}#sub{{padding:14px 50px;font-size:28px;color:#333}}
img{{width:100%;height:700px;object-fit:cover}}
#date{{position:absolute;left:40px;bottom:40px;background:#c00;color:#fff;font-weight:900;font-size:40px;padding:10px 20px}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px}}
</style></head><body><div id="card"><div id="bk">BREAKING</div><div id="hl">{hl}</div>
<div id="sub">{html.escape(sub or "")}</div><img src="data:image/jpeg;base64,{b64}"><div id="date">{date_str}</div></div>
<div id="handle">{settings.ig_handle}</div></body></html>"""

def outro_video():
    cache = Path(settings.output_dir) / "outro.mp4"
    if cache.exists(): return str(cache)
    h = f"""<!doctype html><html><head><style>
*{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial}}
#card{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:900px;background:#1a1a1a;border-radius:20px;padding:50px}}
#row{{display:flex;align-items:center;gap:30px}}#av{{width:130px;height:130px;border-radius:50%;background:radial-gradient(#feda75,#fa7e1e,#d62976,#962fbf);padding:6px}}
#av div{{width:100%;height:100%;border-radius:50%;background:#000;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:40px}}
#nm{{color:#fff;font-weight:800;font-size:44px}}#hd{{color:#999;font-size:30px}}
#btn{{margin-top:44px;background:#3797ef;color:#fff;text-align:center;font-weight:700;font-size:40px;padding:24px;border-radius:12px;animation:fl 1s forwards}}
@keyframes fl{{0%{{opacity:1}}45%{{opacity:1}}55%{{opacity:0}}100%{{opacity:0}}}}
#btn2{{position:absolute;left:50px;right:50px;top:318px;background:#eee;color:#555;text-align:center;font-weight:700;font-size:40px;padding:24px;border-radius:12px;opacity:0;animation:fl2 1s forwards}}
@keyframes fl2{{0%,55%{{opacity:0}}100%{{opacity:1}}}}
#ig{{position:absolute;top:26%;width:100%;text-align:center;font-size:120px;opacity:0;animation:ig 1.2s 1.4s forwards}}
@keyframes ig{{to{{opacity:1}}}}#ig span{{background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf);-webkit-background-clip:text;color:transparent}}
#hdl{{position:absolute;top:40%;width:100%;text-align:center;color:#fff;font-weight:800;font-size:44px;opacity:0;animation:ig 1s 1.6s forwards}}
</style></head><body><div id="card"><div id="row"><div id="av"><div>24</div></div>
<div><div id="nm">indiainlast24hr ✔</div><div id="hd">{settings.ig_handle}</div></div></div>
<div id="btn">Follow</div><div id="btn2">Following ⌄</div></div>
<div id="ig"><span>◎</span></div><div id="hdl">{settings.ig_handle}</div></body></html>"""
    webm = record_html(h, 3.5, "outro")
    import imageio_ffmpeg as ioff, subprocess
    subprocess.run([ioff.get_ffmpeg_exe(), "-y", "-i", webm, "-vf", "fps=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cache)], check=True, capture_output=True)
    return str(cache)

def has_country(name):
    if not name: return False
    n = name.lower()
    return any(n == (f["properties"].get("NAME") or "").lower()
               or n in (f["properties"].get("NAME") or "").lower()
               for f in _geojson()["features"])