import html, os, base64, datetime
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
from .config import settings

RAW = Path(settings.output_dir).resolve() / "raw"
HANDLE_FIX_CSS = "#handle{top:auto!important;bottom:70px!important;right:44px!important}"

def _date_str():
    ist = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    return ist.strftime("%d %b").upper()

def _b64(p): return base64.b64encode(Path(p).read_bytes()).decode()

def record_html(page_html, dur, name):
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / f"{name}.html"; p.write_text(page_html, encoding="utf-8")
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1080, "height": 1920},
                            record_video_dir=str(RAW), record_video_size={"width": 1080, "height": 1920})
        pg = ctx.new_page(); pg.goto(p.resolve().as_uri())
        pg.add_style_tag(content=HANDLE_FIX_CSS)
        pg.wait_for_timeout(int(dur * 1000))
        v = pg.video; pg.close(); out = v.path(); ctx.close(); b.close()
    return out

def spans(text, timings, step=0.3):
    words = text.split(); out = []
    for i, w in enumerate(words):
        d = timings[i][1] + step if i < len(timings) else step + i * 0.35
        out.append(f'<span class="w"><i style="animation-delay:{d:.2f}s"></i><b>{html.escape(w)}</b></span>')
    return " ".join(out)

KARAOKE_CSS = """.w{position:relative;display:inline-block;margin-right:0.25ch}
.w i{position:absolute;left:-2px;right:-0.35ch;top:6%;height:88%;background:#d40000;opacity:.95;transform:scaleX(0);transform-origin:left;animation:hl .16s forwards}
.w b{position:relative;font-weight:inherit}@keyframes hl{to{transform:scaleX(1)}}"""

def _geojson():
    if not hasattr(_geojson, "cache"):
        url = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
        _geojson.cache = httpx.get(url, timeout=60).json()
    return _geojson.cache

def has_country(name):
    if not name: return False
    n = name.lower()
    return any(n == (f["properties"].get("NAME") or "").lower()
               or n in (f["properties"].get("NAME") or "").lower()
               for f in _geojson()["features"])

def map_html(country, pin, overlay_text, dur, lat=None, lon=None, topic_img=None):
    """P7 pro map: terrain texture + gradient country + circular topic photo pin."""
    gj = _geojson()["features"]
    nm = lambda f: (f["properties"].get("NAME") or "").lower()
    target = next((f for f in gj if nm(f) == country.lower()), None)
    if target is None: target = next((f for f in gj if country.lower() in nm(f)), gj[0])
    rings = lambda f: ([p[0] for p in f["geometry"]["coordinates"]] if f["geometry"]["type"] == "MultiPolygon"
                       else [f["geometry"]["coordinates"][0]])
    tr = rings(target)
    txs = [c[0] for r in tr for c in r]; tys = [c[1] for r in tr for c in r]
    if lat is not None and lon is not None:
        cx, cy = lon, lat
    else:
        cx, cy = (min(txs)+max(txs))/2, (min(tys)+max(tys))/2
    w = max(max(txs)-min(txs), 20); pad = w * 2.0
    X = lambda lo: (lo + 180) * 6; Y = lambda la: (90 - la) * 6
    vx, vy, vw, vh = X(cx-pad/2), Y(cy+pad/2), X(cx+pad/2)-X(cx-pad/2), Y(cy-pad/2)-Y(cy+pad/2)
    tex = ""
    tpath = os.path.join(settings.output_dir, "terrain.jpg")
    if topic_img is None and os.path.exists(tpath):
        tex = f'<image href="data:image/jpeg;base64,{_b64(tpath)}" x="0" y="0" width="2160" height="1080" style="filter:grayscale(1) brightness(.45)"/>'
    def path(f, cls):
        d = "".join("M" + "L".join(f"{X(c[0]):.0f} {Y(c[1]):.0f}" for c in r[::2]) + "Z" for r in rings(f))
        return f'<path class="{cls}" d="{d}"/>'
    land = "".join(path(f, "l") for f in gj if f is not target)
    tgt = path(target, "t")
    pinb64 = f'<img src="data:image/jpeg;base64,{_b64(topic_img)}"/>' if topic_img else ""
    pin_html = f"""<div id="pin"><div class="ring">{pinb64}</div>
<div class="lbl">{html.escape(pin or country)}</div></div>""" if (pin or topic_img) else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#050505;overflow:hidden;font-family:Arial}}
#wrap{{position:absolute;inset:0;animation:zm {dur:.1f}s ease-in forwards;transform-origin:50% 50%}}
@keyframes zm{{from{{transform:scale(1)}}to{{transform:scale(1.9)}}}}
svg{{width:100%;height:100%}}
.l{{fill:#141414;stroke:#222;stroke-width:1}}
.t{{fill:url(#g1);stroke:#fff;stroke-width:2.5;filter:drop-shadow(0 0 22px rgba(255,0,255,.55))}}
#vig{{position:absolute;inset:0;background:radial-gradient(circle,transparent 35%,#000 96%)}}
#pin{{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);text-align:center}}
.ring{{width:170px;height:170px;border-radius:50%;border:5px solid #fff;overflow:hidden;margin:0 auto;box-shadow:0 0 40px rgba(255,0,0,.6);background:#222}}
.ring img{{width:100%;height:100%;object-fit:cover}}
.lbl{{margin-top:12px;background:#fff;color:#a00;font-weight:900;font-size:40px;letter-spacing:2px;padding:8px 26px;border-radius:10px;display:inline-block;box-shadow:0 6px 20px #000}}
#ov{{position:absolute;top:26%;width:100%;text-align:center;color:#fff;font-weight:800;font-size:62px;letter-spacing:2px;text-shadow:0 4px 18px #000;text-transform:uppercase}}
#logo{{position:fixed;top:48px;left:48px;color:#fff;font-weight:900;font-size:40px}}#logo b{{color:#e11}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px;text-shadow:0 2px 8px #000}}
</style></head><body>
<div id="wrap"><svg viewBox="{vx:.0f} {vy:.0f} {vw:.0f} {vh:.0f}">
<defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#e100ff"/><stop offset="1" stop-color="#2b32ff"/></linearGradient></defs>
{tex}{land}{tgt}</svg></div>
<div id="vig"></div>{pin_html}
<div id="ov">{html.escape(overlay_text or "")}</div>
<div id="logo">INDIA<b>24</b></div><div id="handle">{settings.ig_handle}</div>
</body></html>"""

def shot_card_html(shot_path, bg_path, source, dur):
    """P7 pro breaking card: REAL page screenshot floating over blurred topic footage-bg."""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial}}
#bg{{position:absolute;inset:-60px;width:1200px;height:2040px;object-fit:cover;filter:blur(28px) brightness(.55);animation:kb {dur:.1f}s linear forwards}}
@keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.12)}}}}
#card{{position:absolute;top:50%;left:50%;width:920px;transform:translate(-50%,-50%) rotate(-1.5deg);
box-shadow:0 40px 90px rgba(0,0,0,.9);animation:pop .5s ease-out}}
#card img{{width:100%;display:block}}
@keyframes pop{{from{{opacity:0;transform:translate(-50%,-50%) rotate(-4deg) scale(.9)}}}}
#src{{position:absolute;top:calc(50% - 330px);left:50%;transform:translateX(-50%);color:#fff;font-weight:800;font-size:30px;letter-spacing:1px;text-shadow:0 2px 10px #000}}
#date{{position:absolute;bottom:150px;left:90px;background:#c00;color:#fff;font-weight:900;font-size:40px;padding:10px 22px}}
#logo{{position:fixed;top:48px;left:48px;color:#fff;font-weight:900;font-size:40px}}#logo b{{color:#e11}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px}}
</style></head><body>
<img id="bg" src="data:image/jpeg;base64,{_b64(bg_path)}"/>
<div id="src">{html.escape(source or "")}</div>
<div id="card"><img src="data:image/png;base64,{_b64(shot_path)}"/></div>
<div id="date">{_date_str()}</div>
<div id="logo">INDIA<b>24</b></div><div id="handle">{settings.ig_handle}</div>
</body></html>"""

def breaking_html(headline, sub, img_path, dur):
    b64 = _b64(img_path)
    words = headline.split(); k = min(6, len(words))
    hl = " ".join(f'<span class="r">{html.escape(w)}</span>' for w in words[:k]) + " " + html.escape(" ".join(words[k:]))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#222;overflow:hidden;font-family:Arial}}
#card{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:950px;background:#fff;animation:pop .4s ease-out}}
@keyframes pop{{from{{opacity:0;transform:translate(-50%,-50%) scale(.9)}}}}
#bk{{font-size:150px;font-weight:900;letter-spacing:-4px;color:#000;padding:40px 50px 0}}
#hl{{padding:10px 50px;font-size:56px;font-weight:800;line-height:1.3;color:#000}}
.r{{background:#d40000;color:#000}}#sub{{padding:14px 50px;font-size:28px;color:#333}}
img{{width:100%;height:700px;object-fit:cover}}
#date{{position:absolute;left:40px;bottom:40px;background:#c00;color:#fff;font-weight:900;font-size:40px;padding:10px 20px}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px}}
</style></head><body><div id="card"><div id="bk">BREAKING</div><div id="hl">{hl}</div>
<div id="sub">{html.escape(sub or "")}</div><img src="data:image/jpeg;base64,{b64}"><div id="date">{_date_str()}</div></div>
<div id="handle">{settings.ig_handle}</div></body></html>"""

def quote_html(text, person, timings, dur):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;box-sizing:border-box}}html,body{{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Georgia,serif}}
#q{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:940px;background:#f5f5f5;padding:60px;font-size:44px;line-height:1.5;color:#141414;box-shadow:0 30px 80px rgba(0,0,0,.8)}}
#p{{margin-top:34px;font:700 40px Arial;color:#111}}{KARAOKE_CSS}
#logo{{position:fixed;top:48px;left:48px;color:#fff;font-weight:900;font-size:40px}}#logo b{{color:#e11}}
#handle{{position:fixed;bottom:70px;right:44px;color:#fff;font-weight:800;font-size:34px}}
</style></head><body><div id="q">{spans(text, timings)}<div id="p">— {html.escape(person)}</div></div>
<div id="logo">INDIA<b>24</b></div><div id="handle">{settings.ig_handle}</div></body></html>"""

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