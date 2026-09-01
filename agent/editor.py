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
from .renderer import CARD
from .schemas import Scene

FF = ioff.get_ffmpeg_exe()

def _font(size: int = 84):
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try: return ImageFont.truetype(name, size)
        except Exception: continue
    try: return ImageFont.load_default(size)
    except Exception: return ImageFont.load_default()

def _probe_dur(src):
    probe = subprocess.run([FF, "-i", src], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", probe.stderr)
    return (int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))) if m else 4.0

def _ensure_audio(src: str) -> str:
    probe = subprocess.run([FF, "-i", src], capture_output=True, text=True)
    if "Audio:" in probe.stderr: return src
    out = src.replace(".mp4", "_a.mp4")
    subprocess.run([FF, "-y", "-i", src, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", out], check=True, capture_output=True)
    return out

def _polish(seg):
    """P6.5 pro-edit: 0.12s dip at each cut = broadcast-style transitions."""
    out = seg.replace(".mp4", "_p.mp4")
    d = _probe_dur(seg)
    subprocess.run([FF, "-y", "-i", seg,
                    "-vf", f"fade=t=in:st=0:d=0.12,fade=t=out:st={max(d-0.15,0):.2f}:d=0.15",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", out],
                   check=True, capture_output=True)
    return out

def _placeholder_img(path: str, text: str):
    img = Image.new("RGB", (1080, 1350), (18, 18, 18))
    d = ImageDraw.Draw(img)
    d.text((540, 675), (text or "BREAKING NEWS")[:26].upper(),
           font=_font(72), fill=(235, 235, 235), anchor="mm")
    img.save(path)

def _is_bad_capture(seg):
    """P6.4 QC GATE (M010): flat mid-gray = dead Playwright canvas."""
    try:
        png = seg + "_qc.png"
        subprocess.run([FF, "-y", "-i", seg, "-vf", "select=eq(n\\,12)", "-frames:v", "1", png],
                       check=True, capture_output=True)
        px = list(Image.open(png).convert("RGB").resize((54, 96)).getdata())
        gray = sum(1 for r, g, b in px if abs(r-128) < 14 and abs(g-128) < 14 and abs(b-128) < 14)
        ratio = gray / len(px)
        if ratio > 0.35:
            logger.warning(f"🧪 QC: {os.path.basename(seg)} gray {ratio:.0%} → rejected, using fallback")
            return True
    except Exception as e:
        logger.warning(f"QC check failed: {e}")
    return False

def _seg_mux(visual, vo, out, dur, blur=False):
    cmd = [FF, "-y", "-i", visual]
    cmd += ["-i", vo["mp3"]] if vo else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    if blur:
        cmd += ["-filter_complex",
                "[0:v]split[fg][bg];"
                "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=18[b];"
                "[fg]scale=1080:-2:flags=lanczos[f];"
                "[b][f]overlay=(W-w)/2:(H-h)/2,fps=30[v]",
                "-map", "[v]", "-map", "1:a"]
    else:
        cmd += ["-vf", "scale=1080:1920:flags=lanczos,fps=30", "-map", "0:v", "-map", "1:a"]
    cmd += ["-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
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
        while True:
            bbox = d.textbbox((0, 0), txt, font=f)
            if (bbox[2] - bbox[0]) <= 960 or size <= 40: break
            size -= 6
            f = _font(size)
        d.text((540, 1560), txt, font=f, fill=(255, 255, 255, 255),
               stroke_width=max(2, size // 20), stroke_fill=(0, 0, 0, 255), anchor="mm")
    img.save(path)

def _norm(w): return re.sub(r"[^a-z0-9\u0900-\u097F]+", "", w.lower())

def _slice(mp3, s, e, out):
    subprocess.run([FF, "-y", "-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", mp3,
                    "-c", "copy", out], check=True, capture_output=True)

def _scene_windows(scenes, words):
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
            logger.error(f"❌ Scene {i} ({sc.type}) failed → skipped: {e}")
    if not segs:
        raise RuntimeError("All scenes failed to render — check logs")
    return segs

def render_scene(scene, i, vo=None):
    from . import scraper
    if vo is None:
        vo = tts.speak(scene.narration, f"s{i}") if scene.narration else None
    dur = vo["dur"] if vo else 4.0
    out = os.path.join(settings.output_dir, f"seg_{i}.mp4")

    if scene.type == "map":
        lat, lon, geo_country = (scraper.geocode(scene.pin) if scene.pin else (None, None, ""))
        country = scene.country or "India"
        use_coords = False
        if geo_country and fx.has_country(geo_country):
            country = geo_country; use_coords = True
        if not fx.has_country(country):
            country = "India"; use_coords = False
        webm = fx.record_html(fx.map_html(country, scene.pin, scene.overlay_text, dur,
                                          lat=lat if use_coords else None,
                                          lon=lon if use_coords else None), dur, f"map{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "clip":
        blurred = True
        clip = clips.get_clip(scene.clip_query or "news", f"s{i}", dur, scene.article_link)
        if not clip and scene.article_link:
            cand = scraper.mobile_record(scene.article_link, f"broll{i}", dur, scroll=True)
            if cand and not _is_bad_capture(cand):
                clip = cand
                blurred = False
        if not clip:
            clip = scraper.commons_video(scene.clip_query or "news",
                                         os.path.join(settings.output_dir, f"cv_{i}.mp4"))
        if not clip: raise RuntimeError("no REAL footage → scene skipped")
        if scene.red_circle or scene.stat_text:
            ov = os.path.join(settings.output_dir, f"ov_{i}.png")
            _overlay_png(scene, ov)
            tmp = os.path.join(settings.output_dir, f"clipov_{i}.mp4")
            subprocess.run([FF, "-y", "-i", clip, "-i", ov, "-filter_complex",
                            "[0:v][1:v]overlay=0:0", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-an", tmp], check=True, capture_output=True)
            clip = tmp
        _seg_mux(clip, vo, out, dur, blur=blurred)

    elif scene.type == "article":
        webm = None
        if scene.article_link and vo:
            webm = scraper.mobile_record(scene.article_link, f"live{i}", dur,
                                         delays=[w[1] + 0.4 for w in vo["words"]])
            if webm and _is_bad_capture(webm):
                webm = None
        if webm:
            _seg_mux(webm, vo, out, dur)
        else:
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
        ok = media.download(scene.image_url, img) if scene.image_url else None
        if not ok and scene.article_link:
            ok = media.download(scraper.main_image_url(scene.article_link), img)
        if not ok:
            ok = clips.get_image(scene.breaking_image_query or scene.breaking_headline, img)
        if not ok:
            _placeholder_img(img, scene.breaking_headline or "")
        _seg_mux(fx.record_html(fx.breaking_html(scene.breaking_headline or "",
                                                 scene.breaking_sub, img, dur),
                                dur, f"b{i}"), vo, out, dur)

    logger.success(f"🎞️ Scene {i} ({scene.type}) rendered")
    return out

def assemble(segments, final):
    if len(segments) < 2:
        raise RuntimeError("Only outro rendered — content scenes failed. Check logs above.")
    segments = [_polish(_ensure_audio(s)) for s in segments]
    listf = os.path.join(settings.output_dir, "segs.txt")
    with open(listf, "w", encoding="utf-8") as f:
        f.write("\n".join(f"file '{Path(s).resolve().as_posix()}'" for s in segments))
    joined = os.path.join(settings.output_dir, "joined.mp4")
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", listf,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2", joined], check=True, capture_output=True)

    T = _probe_dur(joined)
    music = os.path.join("assets", "music.mp3")
    cmd = [FF, "-y", "-i", joined]
    if os.path.exists(music):
        cmd += ["-i", music, "-filter_complex",
                "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a"]
    cmd += ["-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(T-0.6,0):.2f}:d=0.6"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", final]
    subprocess.run(cmd, check=True, capture_output=True)
    logger.success(f"✅ FULL REEL: {final}")