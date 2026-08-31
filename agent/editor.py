import html as _html
import os
import subprocess
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg as ioff
from loguru import logger

from . import fx, tts, clips, media
from .config import settings
from .renderer import CARD          # Phase-1 article card
from .schemas import Scene

FF = ioff.get_ffmpeg_exe()

# ---------------- helpers ----------------
def _font(size: int = 84):
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try: return ImageFont.truetype(name, size)
        except Exception: continue
    try: return ImageFont.load_default(size)
    except Exception: return ImageFont.load_default()

def _ensure_audio(src: str) -> str:
    """Guarantees every segment has an AAC stereo track."""
    probe = subprocess.run([FF, "-i", src], capture_output=True, text=True)
    if "Audio:" in probe.stderr: return src
    out = src.replace(".mp4", "_a.mp4")
    subprocess.run([FF, "-y", "-i", src, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", out], check=True, capture_output=True)
    return out

def _placeholder_img(path: str, text: str):
    img = Image.new("RGB", (1080, 1350), (18, 18, 18))
    d = ImageDraw.Draw(img)
    d.text((540, 675), (text or "BREAKING NEWS")[:26].upper(),
           font=_font(72), fill=(235, 235, 235), anchor="mm")
    img.save(path)

def _seg_mux(visual, vo, out, dur):
    cmd = [FF, "-y", "-i", visual]
    cmd += ["-i", vo["mp3"]] if vo else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-t", f"{dur:.2f}", "-vf", "scale=1080:1920,fps=30",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", out]
    subprocess.run(cmd, check=True, capture_output=True)

def _overlay_png(scene, path):
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if scene.red_circle:
        d.ellipse([240, 660, 840, 1260], outline=(220, 0, 0, 255), width=14)
    if scene.stat_text:
        txt, size = scene.stat_text.upper(), 84
        f = _font(size)
        # Auto-shrink to fit screen (fixes cut-off text)
        while True:
            bbox = d.textbbox((0, 0), txt, font=f)
            if (bbox[2] - bbox[0]) <= 960 or size <= 40: break
            size -= 6
            f = _font(size)
        d.text((540, 1560), txt, font=f, fill=(255, 255, 255, 255),
               stroke_width=max(2, size // 20), stroke_fill=(0, 0, 0, 255), anchor="mm")
    img.save(path)

# ---------------- Phase 5: Single-Take Voice Logic ----------------
def _norm(w): return re.sub(r"[^a-z0-9\u0900-\u097F]+", "", w.lower())

def _slice(mp3, s, e, out):
    subprocess.run([FF, "-y", "-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", mp3,
                    "-c", "copy", out], check=True, capture_output=True)

def _scene_windows(scenes, words):
    """Aligns the single continuous voice take to each scene."""
    # SAFETY NET: If TTS returned no words, make scenes silent (4s each)
    if not words:
        return [None] * len(scenes)
        
    toks = [_norm(w) for w, _, _ in words]
    wins, ptr = [], 0
    for sc in scenes:
        n = len(sc.narration.split()) if sc.narration else 0
        if not n: wins.append(None); continue
        needle = _norm(sc.narration.split()[0])
        start = next((i for i in range(ptr, len(toks)) if toks[i] == needle), ptr)
        end = min(start + n, len(toks))
        s_t = words[start][1] if start < len(words) else 0
        e_t = (words[end-1][2] if end <= len(words) else words[-1][2]) + 0.3
        wins.append((s_t, e_t, [(w, t1-s_t, t2-s_t) for w, t1, t2 in words[start:end]]))
        ptr = end
    return wins

def render_all(scenes, take):
    segs = []
    for i, (sc, w) in enumerate(zip(scenes, _scene_windows(scenes, take["words"]))):
        try:
            vo = None
            if w:
                sp = os.path.join(settings.output_dir, f"vo_s{i}.mp3")
                _slice(take["mp3"], w[0], w[1], sp)
                vo = {"mp3": sp, "words": w[2], "dur": w[1] - w[0] + 0.1}
            segs.append(render_scene(sc, i, vo))
        except Exception as e:
            # SAFETY NET: Skip broken scenes instead of killing the whole reel
            logger.error(f"❌ Scene {i} ({sc.type}) failed → skipped: {e}")
            
    if not segs:
        raise RuntimeError("All scenes failed to render — check logs")
    return segs

# ---------------- per-scene renderer ----------------
def render_scene(scene, i, vo=None):
    if vo is None:
        vo = tts.speak(scene.narration, f"s{i}") if scene.narration else None
    dur = vo["dur"] if vo else 4.0
    out = os.path.join(settings.output_dir, f"seg_{i}.mp4")
    
    if scene.type == "map":
        webm = fx.record_html(fx.map_html(scene.country or "India", scene.pin,
                                          scene.overlay_text, dur), dur, f"map{i}")
        _seg_mux(webm, vo, out, dur)
        
    elif scene.type == "clip":
        clip = clips.get_clip(scene.clip_query or "news", f"s{i}", dur)
        if not clip: raise RuntimeError("no REAL footage found → scene skipped")
        if scene.red_circle or scene.stat_text:
            ov = os.path.join(settings.output_dir, f"ov_{i}.png")
            _overlay_png(scene, ov)
            tmp = os.path.join(settings.output_dir, f"clipov_{i}.mp4")
            subprocess.run([FF, "-y", "-i", clip, "-i", ov, "-filter_complex",
                            "[0:v][1:v]overlay=0:0", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-an", tmp], check=True, capture_output=True)
            clip = tmp
        _seg_mux(clip, vo, out, dur)
        
    elif scene.type == "article":
        words = (scene.headline or "").split()
        delays = ([w[1] + 0.3 for w in vo["words"]][:len(words)] if vo else [0.3 + j * 0.4 for j in range(len(words))])
        while len(delays) < len(words):
            delays.append((delays[-1] + 0.4) if delays else 0.3)
        sp = "".join(f'<span class="w"><i style="animation-delay:{d:.2f}s"></i><b>{_html.escape(w)}</b></span>'
                     for w, d in zip(words, delays))
        page = (CARD.replace("__HANDLE__", settings.ig_handle)
                    .replace("__MASTHEAD__", (scene.masthead or "THE TIMES OF INDIA").upper())
                    .replace("__HEADLINE__", sp)
                    .replace("__META__", scene.masthead or "")
                    .replace("__BIG__", scene.stat_text or ""))
        _seg_mux(fx.record_html(page, dur, f"art{i}"), vo, out, dur)
        
    elif scene.type == "quote":
        _seg_mux(fx.record_html(fx.quote_html(scene.quote_text or "", scene.person or "",
                                              vo["words"] if vo else [], dur), dur, f"q{i}"), vo, out, dur)
                                              
    elif scene.type == "breaking":
        img = os.path.join(settings.output_dir, f"br_{i}.jpg")
        ok = None
        # 1. Try REAL news photo attached by nodes.py
        if scene.image_url:
            ok = media.download(scene.image_url, img)
        # 2. Fallback to search (Stock -> AI)
        if not ok:
            try: ok = clips.get_image(scene.breaking_image_query or scene.breaking_headline, img)
            except Exception: ok = None
        # 3. Final fallback
        if not ok: _placeholder_img(img, scene.breaking_headline or "")
        
        _seg_mux(fx.record_html(fx.breaking_html(scene.breaking_headline or "",
                                                 scene.breaking_sub, img, dur),
                                dur, f"b{i}"), vo, out, dur)
                                
    logger.success(f"🎞️ Scene {i} ({scene.type}) rendered")
    return out

# ---------------- final assembly ----------------
def assemble(segments, final):
    # SAFETY NET: Fail loudly if only the outro exists (no more silent outro-only reels)
    if len(segments) < 2:
        raise RuntimeError("Only outro rendered — content scenes failed. Check logs above.")
        
    segments = [_ensure_audio(s) for s in segments]
    listf = os.path.join(settings.output_dir, "segs.txt")
    with open(listf, "w", encoding="utf-8") as f:
        f.write("\n".join(f"file '{Path(s).resolve().as_posix()}'" for s in segments))
    joined = os.path.join(settings.output_dir, "joined.mp4")
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", listf,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2", joined], check=True, capture_output=True)

    music = os.path.join("assets", "music.mp3")
    cmd = [FF, "-y", "-i", joined]
    if os.path.exists(music):
        cmd += ["-i", music, "-filter_complex",
                "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", final]
    subprocess.run(cmd, check=True, capture_output=True)
    logger.success(f"✅ FULL REEL: {final}")