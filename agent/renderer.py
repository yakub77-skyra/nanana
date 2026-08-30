import html, os, subprocess
import imageio_ffmpeg as ioff
from playwright.sync_api import sync_playwright
from loguru import logger
from .config import settings

from pathlib import Path

CARD = """<!doctype html><html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1920px;background:#000;overflow:hidden;font-family:Arial,Helvetica,sans-serif}
#logo{position:fixed;top:48px;left:48px;color:#fff;font-weight:900;font-size:40px}
#logo b{color:#e11}
#handle{position:fixed;top:34%;right:44px;color:#fff;font-weight:800;font-size:34px;text-shadow:0 2px 8px #000}
#big{position:fixed;bottom:110px;width:100%;text-align:center;color:#fff;font-weight:900;font-size:76px;letter-spacing:2px;text-transform:uppercase;text-shadow:0 4px 14px #000}
#card{position:absolute;top:50%;left:50%;transform:translate(-50%,-52%);width:940px;background:#f7f7f7;border-radius:6px;padding:56px 60px;box-shadow:0 30px 80px rgba(0,0,0,.8);animation:pop .5s ease-out}
@keyframes pop{from{opacity:0;transform:translate(-50%,-50%) scale(.92)}to{opacity:1;transform:translate(-50%,-52%) scale(1)}}
#mast{font-family:Georgia,serif;font-size:46px;font-weight:700;letter-spacing:2px;color:#111;border-bottom:3px solid #111;padding-bottom:18px;display:flex;justify-content:space-between;align-items:center}
#mast .app{background:#c00;color:#fff;font:600 20px Arial;border-radius:6px;padding:8px 16px}
#nav{color:#555;font-size:24px;margin:12px 0 26px;letter-spacing:1px}
h1{font-size:58px;line-height:1.35;color:#141414;font-weight:700}
.w{position:relative;display:inline-block;margin-right:.32ch}
.w i{position:absolute;left:-3px;right:-3px;top:6%;height:88%;background:#d40000;opacity:.95;transform:scaleX(0);transform-origin:left;animation:hl .16s forwards}
.w b{position:relative;font-weight:inherit}
@keyframes hl{to{transform:scaleX(1)}}
#meta{margin-top:26px;color:#777;font-size:22px}
#meta .tag{border:2px solid #999;border-radius:999px;padding:4px 18px;color:#444;margin-right:14px}
</style></head><body>
<div id="logo">INDIA<b>24</b></div><div id="handle">__HANDLE__</div>
<div id="card"><div id="mast"><span>__MASTHEAD__</span><span class="app">Download App</span></div>
<div id="nav">News &nbsp; Videos &nbsp; India &nbsp; World &nbsp; City</div>
<h1>__HEADLINE__</h1>
<div id="meta"><span class="tag">WORLD</span> __META__</div></div>
<div id="big">__BIG__</div></body></html>"""

def _delays(words, timings):
    n = len(words)
    if len(timings) >= n:
        return [t[1] + 0.3 for t in timings[:n]]
    total = timings[-1][2] if timings else 4.0
    return [0.3 + i * total / max(n, 1) for i in range(n)]

def render_karaoke(state):
    a, schema, voice = state["article"], state["schema"], state["voice"]
    source = a["source"] or "THE TIMES OF INDIA"
    title = a["title"]
    if title.lower().endswith(source.lower()):
        title = title[: -len(source)].strip(" -")
    words = title.split()
    delays = _delays(words, voice["words"])
    spans = "".join(
        f'<span class="w"><i style="animation-delay:{d:.2f}s"></i><b>{html.escape(w)}</b></span>'
        for w, d in zip(words, delays))
    page_html = (CARD
        .replace("__HANDLE__", settings.ig_handle)
        .replace("__MASTHEAD__", html.escape(source.upper()))
        .replace("__HEADLINE__", spans)
        .replace("__META__", f"{html.escape(source)} | {a.get('published', '')[:16]}")
        .replace("__BIG__", html.escape(schema["big_text"])))
    html_path = os.path.abspath(os.path.join(settings.output_dir, "card.html"))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page_html)

    duration = (voice["words"][-1][2] if voice["words"] else 5.0) + 1.5
    raw_dir = os.path.join(settings.output_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1080, "height": 1920},
                                  record_video_dir=raw_dir,
                                  record_video_size={"width": 1080, "height": 1920})
        page = ctx.new_page()
        page.goto(Path(html_path).as_uri())
        page.wait_for_timeout(int(duration * 1000))
        video = page.video
        page.close()
        raw_path = video.path()
        ctx.close(); browser.close()
    logger.info("🎬 Card animation recorded")
    return {"raw_video": raw_path}

def mux_output(state):
    out = os.path.join(settings.output_dir, "reel_phase1.mp4")
    cmd = [ioff.get_ffmpeg_exe(), "-y", "-i", state["raw_video"], "-i", state["voice"]["mp3"],
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, capture_output=True)
    logger.success(f"✅ FINAL REEL: {out}")
    return {"final": out}
