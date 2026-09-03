import html as _html
import os, subprocess, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg as ioff
from loguru import logger
from . import fx, tts, clips, media, scraper
from .config import settings
from .schemas import Scene

FF = ioff.get_ffmpeg_exe()
FEED_IMAGES = []   # [(title, og_url)] populated by nodes.render_scenes

def _font(size=84):
    for n in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()

def _cut(s, n):
    s = s or ""
    if len(s) <= n:
        return s
    cut = s[:n]
    cut = cut[:cut.rfind(" ")] or cut
    words = cut.split()
    bad = {"A","AN","THE","OF","TO","IN","FOR","WITH","ON","AT","S","AND","OR","AS","BY","FROM"}
    while words and (words[-1].upper().strip(".") in bad or words[-1].upper().endswith("'S") or words[-1].endswith(",")):
        words.pop()
    return " ".join(words).strip()

def _probe_dur(src):
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)",
                  subprocess.run([FF, "-i", src], capture_output=True, text=True).stderr)
    return (int(m.group(1))*3600 + int(m.group(2))*60 + float(m.group(3))) if m else 4.0

def _ensure_audio(src):
    if "Audio:" in subprocess.run([FF, "-i", src], capture_output=True, text=True).stderr:
        return src
    out = src.replace(".mp4", "_a.mp4")
    subprocess.run([FF, "-y", "-i", src, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", out],
                   check=True, capture_output=True)
    return out

def _polish(seg):
    out = seg.replace(".mp4", "_p.mp4")
    d = _probe_dur(seg)
    subprocess.run([FF, "-y", "-i", seg,
                    "-vf", f"fade=t=in:st=0:d=0.12,fade=t=out:st={max(d-0.15,0):.2f}:d=0.15",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", out],
                   check=True, capture_output=True)
    return out

def _is_bad_capture(seg):
    try:
        png = seg + "_qc.png"
        subprocess.run([FF, "-y", "-i", seg, "-vf", "select=eq(n,12)", "-frames:v", "1", png],
                       check=True, capture_output=True)
        px = list(Image.open(png).convert("RGB").resize((54, 96)).getdata())
        ratio = sum(1 for r, g, b in px if abs(r-128) < 14 and abs(g-128) < 14 and abs(b-128) < 14) / len(px)
        if ratio > 0.35:
            logger.warning(f"QC: {os.path.basename(seg)} gray {ratio:.0%} -> rejected")
            return True
    except Exception:
        pass
    return False

def _seg_mux(visual, vo, out, dur, blur=False):
    cmd = [FF, "-y", "-i", visual]
    cmd += ["-i", vo["mp3"]] if vo else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    if blur:
        cmd += ["-filter_complex",
                "[0:v]split[fg][bg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=18[b];"
                "[fg]scale=1080:-2:flags=lanczos[f];[b][f]overlay=(W-w)/2:(H-h)/2,fps=30[v]",
                "-map", "[v]", "-map", "1:a"]
    else:
        cmd += ["-vf", "scale=1080:1920:flags=lanczos,fps=30", "-map", "0:v", "-map", "1:a"]
    cmd += ["-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", out]
    subprocess.run(cmd, check=True, capture_output=True)

def _slice(mp3, s, e, out):
    subprocess.run([FF, "-y", "-ss", f"{s:.2f}", "-to", f"{e:.2f}", "-i", mp3, "-c", "copy", out],
                   check=True, capture_output=True)

def _norm(w):
    return re.sub(r"[^a-z0-9\u0900-\u097F]+", "", w.lower())

def _scene_windows(scenes, words):
    if not words:
        return [None] * len(scenes)
    toks = [_norm(w) for w, _, _ in words]
    wins, ptr = [], 0
    for sc in scenes:
        n = len(sc.narration.split()) if sc.narration else 0
        if not n:
            wins.append(None)
            continue
        needle = _norm(sc.narration.split()[0])
        start = next((i for i in range(ptr, len(toks)) if toks[i] == needle), ptr)
        end = min(start + n, len(toks))
        s_t = words[start][1] if start < len(words) else 0
        e_t = (words[end-1][2] if end <= len(words) else words[-1][2]) + 0.3
        wins.append((s_t, e_t, [(w, t1-s_t, t2-s_t) for w, t1, t2 in words[start:end]]))
        ptr = end
    return wins

def _get_bg_image(scene, i):
    """Get background image for a scene."""
    img = os.path.join(settings.output_dir, f"bg_{i}.jpg")
    q = scene.clip_query or scene.breaking_image_query or scene.breaking_headline or "news"
    ok = media.download(scene.image_url, img) if scene.image_url else None
    if not ok and scene.article_link:
        ok = media.download(scraper.main_image_url(scene.article_link), img)
    if not ok:
        ok = media.commons_image(q, img)
    return img if ok else None

def _get_photo_b64(scene, i):
    """Robust photo chain: scene url → article main → article og → matching feed og →
    first feed og → openverse → commons → (empty = gradient fallback)."""
    img_path = os.path.join(settings.output_dir, f"photo_{i}.jpg")
    q = scene.clip_query or scene.breaking_image_query or scene.breaking_headline or "news"
    ok = media.download(scene.image_url, img_path) if scene.image_url else None
    if not ok and scene.article_link:
        ok = media.download(scraper.main_image_url(scene.article_link), img_path)
    if not ok and scene.article_link:
        ok = media.download(media.og_image(scene.article_link), img_path)
    if not ok:
        words = [w for w in (scene.headline or scene.breaking_headline or "").lower().split() if len(w) > 3]
        pool = sorted(FEED_IMAGES, key=lambda t: -sum(w in t[0].lower() for w in words))
        for _, url in pool:
            if url and media.download(url, img_path):
                ok = img_path
                break
    if not ok:
        ok = media.openverse_image(q, img_path)
    if not ok:
        ok = media.commons_image(q, img_path)
    if ok and os.path.exists(img_path):
        return fx._b64_or_empty(img_path)
    return ""

def _get_footage_b64(scene, i, dur):
    """Get footage frame as base64 for HTML scenes."""
    clip = clips.get_clip(scene.clip_query or "news", f"frame_{i}", min(dur, 3), scene.article_link)
    if clip and os.path.exists(clip):
        frame_path = os.path.join(settings.output_dir, f"frame_{i}.jpg")
        subprocess.run([FF, "-y", "-i", clip, "-vf", "select=eq(n,5)", "-frames:v", "1", frame_path],
                       check=True, capture_output=True)
        if os.path.exists(frame_path):
            return fx._b64_or_empty(frame_path)
    return _get_photo_b64(scene, i)

def render_all(scenes, take=None, fmt="deep_dive"):
    segs, seen_q = [], set()
    words = (take or {}).get("words") or []
    wins = _scene_windows(scenes, words) if words else [None] * len(scenes)
    for i, (sc, w) in enumerate(zip(scenes, wins)):
        if sc.type == "quote" or sc.type == "quote_card":
            key = (sc.quote_text or "").strip()[:100]
            if not key or key in seen_q:
                continue
            seen_q.add(key)
        try:
            vo = None
            if w:
                sp = os.path.join(settings.output_dir, f"vo_s{i}.mp3")
                _slice(take["mp3"], w[0], w[1], sp)
                vo = {"mp3": sp, "words": w[2], "dur": w[1] - w[0] + 0.1}
            segs.append(render_scene(sc, i, vo, fmt=fmt))
        except Exception as e:
            logger.error(f"Scene {i} ({sc.type}) failed -> skipped: {e}")
    if not segs:
        raise RuntimeError("All scenes failed")
    return segs

def render_scene(scene, i, vo=None, fmt="deep_dive"):
    if vo is None:
        vo = tts.speak(scene.narration, f"s{i}") if scene.narration else None
    dur = vo["dur"] if vo else 4.0
    out = os.path.join(settings.output_dir, f"seg_{i}.mp4")

    # NEW SCENE TYPES (matching video style)
    if scene.type == "title_card":
        text = scene.overlay_text or scene.headline or scene.breaking_headline or "BREAKING NEWS"
        html = fx.title_card_html(text, dur, theme=scene.theme or "purple")
        webm = fx.record_html(html, dur, f"tc{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "map_intro":
        country = scene.country or "India"
        pin = scene.pin
        overlay = scene.overlay_text or _cut(scene.headline or "INDIA NEWS", 44).upper()
        theme = scene.theme or "purple"
        topic_img = None
        if pin:
            timg = os.path.join(settings.output_dir, f"pin_{i}.jpg")
            if media.commons_image((scene.clip_query or pin or "india")[:40], timg):
                topic_img = timg
        html = fx.map_intro_html(country, overlay, dur, theme=theme, topic_img=topic_img, pin=pin)
        webm = fx.record_html(html, dur, f"map{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "news_frame":
        photo_b64 = _get_photo_b64(scene, i)
        style = scene.style or ("roundup" if fmt == "roundup" else "deep")
        html = fx.news_frame_html(
            scene.frame_number or (i + 1),
            scene.headline or scene.breaking_headline or "HEADLINE",
            photo_b64,
            scene.location or scene.pin or "INDIA",
            dur,
            theme=scene.theme or "purple",
            style=style,
            state=scene.state or None
        )
        webm = fx.record_html(html, dur, f"nf{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "article_card":
        bg_img = _get_bg_image(scene, i)
        bg_b64 = fx._b64_or_empty(bg_img) if bg_img else ""
        html = fx.article_card_html(
            scene.masthead or scene.breaking_sub or "NEWS SOURCE",
            scene.headline or scene.breaking_headline or "HEADLINE",
            scene.category or "NEWS",
            scene.date_str or "",
            bg_b64,
            dur,
            source_color=scene.source_color or "#c00"
        )
        webm = fx.record_html(html, dur, f"ac{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "location_highlight":
        photo_b64 = _get_photo_b64(scene, i)
        html = fx.location_highlight_html(
            scene.country or "India",
            scene.pin or scene.location or "LOCATION",
            photo_b64,
            scene.overlay_text or scene.headline or "",
            dur,
            theme=scene.theme or "red"
        )
        webm = fx.record_html(html, dur, f"lh{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "disaster_dramatic":
        footage_b64 = _get_footage_b64(scene, i, dur)
        html = fx.disaster_dramatic_html(
            scene.breaking_headline or scene.headline or "BREAKING",
            scene.sub_text or scene.breaking_sub or "",
            footage_b64,
            dur
        )
        webm = fx.record_html(html, dur, f"dd{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "footage_highlight":
        footage_b64 = _get_footage_b64(scene, i, dur)
        html = fx.footage_highlight_html(
            footage_b64,
            scene.circle_x or 540,
            scene.circle_y or 960,
            scene.circle_r or 200,
            scene.label_text or "",
            dur
        )
        webm = fx.record_html(html, dur, f"fh{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "breaking_card":
        img_b64 = _get_photo_b64(scene, i)
        html = fx.breaking_card_html(
            scene.breaking_headline or scene.headline or "BREAKING NEWS",
            scene.breaking_sub or "",
            img_b64,
            dur,
            source=scene.masthead or ""
        )
        webm = fx.record_html(html, dur, f"bc{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "quote_card":
        html = fx.quote_card_html(
            scene.quote_text or "",
            scene.person or "",
            dur,
            theme=scene.theme or "purple"
        )
        webm = fx.record_html(html, dur, f"qc{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "stat_overlay":
        footage_b64 = _get_footage_b64(scene, i, dur) or ""
        html = fx.stat_overlay_html(
            scene.stat_text or "0",
            scene.stat_label or "",
            footage_b64,
            dur,
            theme=scene.theme or "purple"
        )
        webm = fx.record_html(html, dur, f"so{i}")
        _seg_mux(webm, vo, out, dur)

    # LEGACY SCENE TYPES (backward compatibility)
    elif scene.type == "map":
        lat, lon, geo_country = (scraper.geocode(scene.pin) if scene.pin else (None, None, ""))
        country = scene.country or "India"
        use = False
        if geo_country and fx.has_country(geo_country):
            country, use = geo_country, True
        if not fx.has_country(country):
            country, use = "India", False
        timg = os.path.join(settings.output_dir, f"pin_{i}.jpg")
        timg = timg if media.commons_image((scene.clip_query or scene.pin or "india")[:40], timg) else None
        if not os.path.exists(os.path.join(settings.output_dir, "terrain.jpg")):
            scraper.commons_texture(os.path.join(settings.output_dir, "terrain.jpg"))
        webm = fx.record_html(fx.map_html(country, scene.pin, _cut(scene.overlay_text, 44).upper(),
                                          dur, lat=lat if use else None, lon=lon if use else None,
                                          topic_img=timg), dur, f"map{i}")
        _seg_mux(webm, vo, out, dur)

    elif scene.type == "clip":
        blurred = True
        clip = clips.get_clip(scene.clip_query or "news", f"s{i}", dur, scene.article_link)
        if not clip and scene.article_link:
            cand = scraper.mobile_record(scene.article_link, f"broll{i}", dur, scroll=True)
            if cand and not _is_bad_capture(cand):
                clip, blurred = cand, False
        if not clip:
            clip = scraper.commons_video(scene.clip_query or "news",
                                         os.path.join(settings.output_dir, f"cv_{i}.mp4"))
        if not clip:
            raise RuntimeError("no REAL footage")
        if scene.red_circle or scene.stat_text:
            ov = os.path.join(settings.output_dir, f"ov_{i}.png")
            _overlay_png(scene, ov)
            tmp = os.path.join(settings.output_dir, f"clipov_{i}.mp4")
            subprocess.run([FF, "-y", "-i", clip, "-i", ov, "-filter_complex", "[0:v][1:v]overlay=0:0",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", tmp],
                           check=True, capture_output=True)
            clip = tmp
        _seg_mux(clip, vo, out, dur, blur=blurred)

    elif scene.type == "article":
        webm = None
        if scene.article_link and vo:
            cand = scraper.mobile_record(scene.article_link, f"live{i}", dur,
                                         delays=[w[1] + 0.4 for w in vo["words"]])
            if cand and not _is_bad_capture(cand):
                webm = cand
        if webm:
            _seg_mux(webm, vo, out, dur)
        else:
            from .renderer import CARD
            words = (scene.headline or "").split()
            delays = ([w[1] + 0.3 for w in vo["words"]][:len(words)] if vo else [0.3 + j*0.4 for j in range(len(words))])
            while len(delays) < len(words):
                delays.append((delays[-1] + 0.4) if delays else 0.3)
            sp = "".join(f'<span class="w"><i style="animation-delay:{d:.2f}s"></i><b>{_html.escape(w)}</b></span>'
                         for w, d in zip(words, delays))
            page = (CARD.replace("__HANDLE__", settings.ig_handle)
                        .replace("__MASTHEAD__", (scene.masthead or "THE TIMES OF INDIA").upper())
                        .replace("__HEADLINE__", sp).replace("__META__", scene.masthead or "")
                        .replace("__BIG__", scene.stat_text or ""))
            _seg_mux(fx.record_html(page, dur, f"art{i}"), vo, out, dur)

    elif scene.type == "quote":
        _seg_mux(fx.record_html(fx.quote_html(scene.quote_text or "", scene.person or "",
                                              vo["words"] if vo else [], dur), dur, f"q{i}"), vo, out, dur)

    elif scene.type == "breaking":
        head = _cut(scene.breaking_headline or "", 60).upper()
        bg = _get_bg_image(scene, i)
        shot = scraper.page_screenshot(scene.article_link) if scene.article_link else None
        if shot and bg:
            _seg_mux(fx.record_html(fx.shot_card_html(shot, bg, scene.breaking_sub or "", dur),
                                    dur, f"b{i}"), vo, out, dur)
        else:
            img = bg or os.path.join(settings.output_dir, f"br_{i}.jpg")
            if not bg:
                ok = media.download(scene.image_url, img) if scene.image_url else None
                if not ok:
                    ok = clips.get_image(scene.breaking_image_query or head, img)
                if not ok:
                    Image.new("RGB", (1080, 1350), (18, 18, 18)).save(img)
            _seg_mux(fx.record_html(fx.breaking_html(head, scene.breaking_sub, img, dur),
                                    dur, f"b{i}"), vo, out, dur)

    logger.success(f"Scene {i} ({scene.type}) rendered")
    return out

def _overlay_png(scene, path):
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if scene.stat_text:
        txt, size = scene.stat_text.upper(), 84
        f = _font(size)
        while True:
            bb = d.textbbox((0, 0), txt, font=f)
            if (bb[2]-bb[0]) <= 900 or size <= 40:
                break
            size -= 6
            f = _font(size)
        d.text((540, 1560), txt, font=f, fill=(255,255,255,255),
               stroke_width=max(2, size//20), stroke_fill=(0,0,0,255), anchor="mm")
        bb = d.textbbox((540, 1560), txt, font=f, anchor="mm")
        d.ellipse([bb[0]-35, bb[1]-28, bb[2]+35, bb[3]+28], outline=(220,0,0,255), width=10)
        d.line([bb[2]+140, bb[1]-160, bb[2]+40, bb[1]-20], fill=(220,0,0,255), width=9)
        d.polygon([(bb[2]+40, bb[1]-20), (bb[2]+70, bb[1]-52), (bb[2]+78, bb[1]-8)], fill=(220,0,0,255))
    if scene.red_circle:
        d.ellipse([240, 660, 840, 1260], outline=(220,0,0,255), width=14)
    img.save(path)

def assemble(segments, final):
    if len(segments) < 2:
        raise RuntimeError("Only outro rendered")
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
        cmd += ["-i", music, "-filter_complex", "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a"]
    cmd += ["-vf", f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(T-0.6,0):.2f}:d=0.6"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", final]
    subprocess.run(cmd, check=True, capture_output=True)
    logger.success(f"FULL REEL: {final}")