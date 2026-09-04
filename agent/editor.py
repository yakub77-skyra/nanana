import html as _html
import os, subprocess, re, base64
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg as ioff
from loguru import logger
from . import fx, tts, clips, media, scraper
from .config import settings
from .schemas import Scene

FF = ioff.get_ffmpeg_exe()
FEED_IMAGES = []
USED_MEDIA = set()

def _font(size=84):
    for n in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try: return ImageFont.truetype(n, size)
        except Exception: continue
    try: return ImageFont.load_default(size)
    except Exception: return ImageFont.load_default()

def _cut(s, n):
    s = s or ""
    if len(s) <= n: return s
    cut = s[:n]; cut = cut[:cut.rfind(" ")] or cut
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

def _norm(w): return re.sub(r"[^a-z0-9\u0900-\u097F]+", "", w.lower())

def _scene_windows(scenes, words):
    if not words: return [None] * len(scenes)
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

def _validate_video(path):
    if not path or not os.path.exists(path): return False
    try:
        res = subprocess.run([FF, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=noprint_wrappers=1:nokey=1", path],
                             capture_output=True, text=True)
        return float(res.stdout.strip() or 0) > 0.5
    except Exception: return False

def _ken_burns_mp4(img_path, out_path, dur):
    subprocess.run([FF, "-y", "-loop", "1", "-i", img_path,
                    "-vf", f"scale=1400:-2,zoompan=z='min(zoom+0.002,1.2)':d={int(dur*30)}:s=1080x1920:fps=30",
                    "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path],
                   check=True, capture_output=True)

def _get_bg_image(scene, i):
    img = os.path.join(settings.output_dir, f"bg_{i}.jpg")
    q = scene.clip_query or scene.breaking_image_query or scene.breaking_headline or "news"
    ok = media.download(scene.image_url, img) if scene.image_url else None
    if not ok and scene.article_link: ok = media.download(scraper.main_image_url(scene.article_link), img)
    if not ok: ok = media.commons_image(q, img)
    return img if ok else None

def _get_photo_b64(scene, i):
    """url -> article main -> article og -> matched feed -> first unused feed -> openverse -> commons"""
    img_path = os.path.join(settings.output_dir, f"photo_{i}.jpg")
    q = scene.clip_query or scene.breaking_image_query or scene.breaking_headline or "news"
    ok = media.download(scene.image_url, img_path) if scene.image_url else None
    if not ok and scene.article_link: ok = media.download(scraper.main_image_url(scene.article_link), img_path)
    if not ok and scene.article_link: ok = media.download(media.og_image(scene.article_link), img_path)
    if not ok:
        words = [w for w in (scene.headline or scene.breaking_headline or "").lower().split() if len(w) > 3]
        best = None
        for title, url in FEED_IMAGES:
            if not url or url in USED_MEDIA: continue
            score = sum(w in title.lower() for w in words)
            if score >= 2 and (best is None or score > best[0]): best = (score, url)
        if best: ok = media.download(best[1], img_path)
    if not ok:
        for title, url in FEED_IMAGES:
            if url and url not in USED_MEDIA and media.download(url, img_path):
                ok = img_path; break
    if not ok: ok = media.openverse_image(q, img_path)
    if not ok: ok = media.commons_image(q, img_path)
    if ok and os.path.exists(img_path):
        USED_MEDIA.add(url if (ok == img_path and 'url' in dir()) else "")
        return fx._b64_or_empty(img_path)
    return ""

def _scene_video(scene, i, dur):
    """Real clip pipeline: article embed -> pexels -> archive -> ken-burns. Validated + deduped."""
    out_path = os.path.join(settings.output_dir, f"vid_{i}.mp4")
    if scene.article_link and scene.article_link not in USED_MEDIA:
        embed_url = media.article_video(scene.article_link)
        if embed_url and embed_url not in USED_MEDIA:
            if media.download(embed_url, out_path) and _validate_video(out_path):
                USED_MEDIA.add(embed_url); return out_path
    pex = os.path.join(settings.output_dir, f"pexels_{i}.mp4")
    got = media.pexels_video(scene.clip_query or scene.headline, pex)
    if got and _validate_video(pex) and pex not in USED_MEDIA:
        USED_MEDIA.add(pex); return pex
    clip = clips.get_clip(scene.clip_query or "news", f"frame_{i}", min(dur, 3), scene.article_link)
    if clip and _validate_video(clip): return clip
    img_path = os.path.join(settings.output_dir, f"photo_{i}.jpg")
    if _get_photo_b64(scene, i) and os.path.exists(img_path):
        kb = os.path.join(settings.output_dir, f"kb_{i}.mp4")
        try:
            _ken_burns_mp4(img_path, kb, dur)
            if _validate_video(kb): return kb
        except Exception: pass
    return ""

def render_all(scenes, take=None, fmt="deep_dive"):
    USED_MEDIA.clear()
    segs, seen_q = [], set()
    words = (take or {}).get("words") or []
    wins = _scene_windows(scenes, words) if words else [None] * len(scenes)
    for i, (sc, w) in enumerate(zip(scenes, wins)):
        if sc.type in ("quote", "quote_card"):
            key = (sc.quote_text or "").strip()[:100]
            if not key or key in seen_q: continue
            seen_q.add(key)
        try:
            vo = None
            if w and take:
                sp = os.path.join(settings.output_dir, f"vo_s{i}.mp3")
                _slice(take["mp3"], w[0], w[1], sp)
                vo = {"mp3": sp, "words": w[2], "dur": w[1] - w[0] + 0.1}
            segs.append(render_scene(sc, i, vo, fmt=fmt))
        except Exception as e:
            logger.error(f"Scene {i} ({sc.type}) failed -> skipped: {e}")
    if not segs: raise RuntimeError("All scenes failed")
    return segs

def render_scene(scene, i, vo=None, fmt="deep_dive"):
    if vo is None:
        vo = tts.speak(scene.narration, f"s{i}") if scene.narration else None
    dur = vo["dur"] if vo else 4.0
    out = os.path.join(settings.output_dir, f"seg_{i}.mp4")

    if scene.type == "title_card":
        text = scene.overlay_text or scene.headline or scene.breaking_headline or "BREAKING NEWS"
        html = fx.title_card_html(text, dur, theme=scene.theme or "purple")
        webm = fx.record_html(html, dur, f"tc{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "map_intro":
        country = scene.country or "India"
        overlay = scene.overlay_text or _cut(scene.headline or "INDIA NEWS", 44).upper()
        html = fx.map_intro_html(country, overlay, dur, theme=scene.theme or "purple")
        webm = fx.record_html(html, dur, f"map{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "news_frame":
        style = scene.style or ("roundup" if fmt == "roundup" else "deep")
        map_pack = None
        if style == "roundup" and scene.state:
            from . import maps
            map_pack = maps.build_state_pack(scene.state)
        video_path = _scene_video(scene, i, dur)
        video_b64 = base64.b64encode(Path(video_path).read_bytes()).decode() if video_path else ""
        photo_b64 = _get_photo_b64(scene, i)
        html = fx.news_frame_html(
            scene.frame_number or (i + 1),
            scene.headline or scene.breaking_headline or "HEADLINE",
            photo_b64, scene.location or scene.pin or "INDIA", dur,
            theme=scene.theme or "purple", style=style, state=scene.state or None,
            video_b64=video_b64, video_mime="video/mp4", map_pack=map_pack)
        webm = fx.record_html(html, dur, f"nf{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "article_card":
        bg_img = _get_bg_image(scene, i)
        bg_b64 = fx._b64_or_empty(bg_img) if bg_img else ""
        html = fx.article_card_html(scene.masthead or scene.breaking_sub or "NEWS SOURCE",
            scene.headline or scene.breaking_headline or "HEADLINE", scene.category or "NEWS",
            scene.date_str or "", bg_b64, dur, source_color=scene.source_color or "#111")
        webm = fx.record_html(html, dur, f"ac{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "keyword_text":
        html = fx.keyword_text_html(scene.keyword or scene.headline or "NEWS",
                                    _scene_video(scene, i, dur) and base64.b64encode(Path(_scene_video(scene, i, dur)).read_bytes()).decode() or "", dur)
        webm = fx.record_html(html, dur, f"kw{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "stat_callout":
        vp = _scene_video(scene, i, dur)
        vb = base64.b64encode(Path(vp).read_bytes()).decode() if vp else ""
        html = fx.stat_callout_html(scene.stat_text or "0", scene.stat_label or "", vb, dur,
                                    theme=scene.theme or "purple", extra_lines=scene.extra_lines or [],
                                    photo_b64=_get_photo_b64(scene, i))
        webm = fx.record_html(html, dur, f"sc{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "table_card":
        html = fx.table_card_html(scene.table_title or "DATA", scene.table_rows or [], dur)
        webm = fx.record_html(html, dur, f"tb{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "location_highlight":
        html = fx.location_highlight_html(scene.country or "India", scene.pin or scene.location or "LOCATION",
            _get_photo_b64(scene, i), scene.overlay_text or scene.headline or "", dur, theme=scene.theme or "red")
        webm = fx.record_html(html, dur, f"lh{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "disaster_dramatic":
        vp = _scene_video(scene, i, dur)
        vb = base64.b64encode(Path(vp).read_bytes()).decode() if vp else ""
        html = fx.disaster_dramatic_html(scene.breaking_headline or scene.headline or "BREAKING",
                                         scene.sub_text or scene.breaking_sub or "", vb, dur)
        webm = fx.record_html(html, dur, f"dd{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "footage_highlight":
        vp = _scene_video(scene, i, dur)
        vb = base64.b64encode(Path(vp).read_bytes()).decode() if vp else ""
        html = fx.footage_highlight_html(vb, scene.circle_x or 540, scene.circle_y or 960,
                                         scene.circle_r or 200, scene.label_text or "", dur)
        webm = fx.record_html(html, dur, f"fh{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "breaking_card":
        html = fx.breaking_card_html(scene.breaking_headline or scene.headline or "BREAKING NEWS",
            scene.breaking_sub or "", _get_photo_b64(scene, i), dur, source=scene.masthead or "")
        webm = fx.record_html(html, dur, f"bc{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "quote_card":
        html = fx.quote_card_html(scene.quote_text or "", scene.person or "", dur, theme=scene.theme or "purple")
        webm = fx.record_html(html, dur, f"qc{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "stat_overlay":
        vp = _scene_video(scene, i, dur)
        vb = base64.b64encode(Path(vp).read_bytes()).decode() if vp else ""
        html = fx.stat_overlay_html(scene.stat_text or "0", scene.stat_label or "", vb, dur, theme=scene.theme or "purple")
        webm = fx.record_html(html, dur, f"so{i}"); _seg_mux(webm, vo, out, dur)

    elif scene.type == "clip":
        blurred = True
        clip = clips.get_clip(scene.clip_query or "news", f"s{i}", dur, scene.article_link)
        if not clip and scene.article_link:
            cand = scraper.mobile_record(scene.article_link, f"broll{i}", dur, scroll=True)
            if cand and not _is_bad_capture(cand): clip, blurred = cand, False
        if not clip:
            clip = scraper.commons_video(scene.clip_query or "news", os.path.join(settings.output_dir, f"cv_{i}.mp4"))
        if not clip: raise RuntimeError("no REAL footage")
        _seg_mux(clip, vo, out, dur, blur=blurred)

    logger.success(f"Scene {i} ({scene.type}) rendered")
    return out

def _is_bad_capture(seg):
    try:
        png = seg + "_qc.png"
        subprocess.run([FF, "-y", "-i", seg, "-vf", "select=eq(n\\,12)", "-frames:v", "1", png],
                       check=True, capture_output=True)
        px = list(Image.open(png).convert("RGB").resize((54, 96)).getdata())
        ratio = sum(1 for r, g, b in px if abs(r-128) < 14 and abs(g-128) < 14 and abs(b-128) < 14) / len(px)
        if ratio > 0.35: return True
    except Exception: pass
    return False

def assemble(segments, final):
    if len(segments) < 2: raise RuntimeError("Only outro rendered")
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
    if not os.path.exists(music):
        try:
            os.makedirs("assets", exist_ok=True)
            subprocess.run([FF, "-y", "-f", "lavfi", "-i", "sine=frequency=110:duration=240",
                            "-f", "lavfi", "-i", "sine=frequency=164.8:duration=240",
                            "-filter_complex", "[0:a][1:a]amix=inputs=2,volume=0.4",
                            "-q:a", "9", music], check=True, capture_output=True)
        except Exception: pass
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