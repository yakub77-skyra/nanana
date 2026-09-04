import os, re, shutil, subprocess
from pathlib import Path
import httpx
import imageio_ffmpeg as ioff
from loguru import logger
from .config import settings
from . import media

FF = ioff.get_ffmpeg_exe()

def _ffmpeg_dir():
    d = os.path.join(settings.output_dir, "ffbin")
    dst = os.path.join(d, "ffmpeg" + (".exe" if os.name == "nt" else ""))
    if not os.path.exists(dst):
        try:
            os.makedirs(d, exist_ok=True)
            shutil.copy(FF, dst)
            os.chmod(dst, 0o755)
        except Exception:
            return None
    return d

def _safe_name(s):
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s or "clip")
    return s[:60] or "clip"

def _terms(query):
    return [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", query or "")]

def _looks_related(title, query):
    title_l = (title or "").lower()
    terms = _terms(query)
    if not terms: return True
    return sum(1 for t in terms if t in title_l) >= min(2, len(terms))

def _trim_to_916(src, out, dur):
    cmd = [FF, "-y", "-i", src, "-vf",
           "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
           "-t", f"{dur:.2f}", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out if os.path.exists(out) else None

def kenburns(img, out, dur):
    cmd = [FF, "-y", "-loop", "1", "-i", img,
           "-vf", f"scale=1400:-2,zoompan=z='min(zoom+0.0018,1.35)':d={int(dur*30)}:s=1080x1920:fps=30",
           "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True, capture_output=True)
    return out

def viral_clip(query, tag, dur=8):
    if not settings.allow_viral_clips: return None
    try: import yt_dlp
    except Exception: return None
    raw = os.path.join(settings.output_dir, f"{_safe_name(tag)}_yt.%(ext)s")
    final = os.path.join(settings.output_dir, f"{_safe_name(tag)}_yt.mp4")
    try:
        opts = {"quiet": True, "format": "best[ext=mp4]/best", "outtmpl": raw, "noplaylist": True,
                "download_ranges": lambda info, ydl: [{"start_time": 5, "end_time": 5 + dur}]}
        ffdir = _ffmpeg_dir()
        if ffdir: opts["ffmpeg_location"] = ffdir
        try:
            with yt_dlp.YoutubeDL(opts) as y: y.download([f"ytsearch1:{query} news"])
        except Exception:
            opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
            with yt_dlp.YoutubeDL(opts) as y: y.download([f"ytsearch1:{query} news"])
        candidates = [str(p) for p in Path(settings.output_dir).glob(f"{_safe_name(tag)}_yt.*")
                      if p.suffix.lower() in {".mp4", ".webm", ".mkv"}]
        if not candidates: return None
        return _trim_to_916(candidates[0], final, dur)
    except Exception as e:
        logger.warning(f"viral clip failed → next source ({e})")
        return None

def archive_clip(query, tag, dur=8):
    try:
        q = " ".join(_terms(query)[:5]) or "news"
        r = httpx.get("https://archive.org/advancedsearch.php", timeout=20,
                      params={"q": f'title:({q}) AND mediatype:(movies)', "fl[]": ["identifier", "title", "year"],
                              "rows": 8, "page": 1, "output": "json"})
        docs = ((r.json().get("response") or {}).get("docs") or [])
        docs = [d for d in docs if _looks_related(d.get("title", ""), query)]
        for d in docs:
            identifier = d.get("identifier")
            if not identifier: continue
            meta = httpx.get(f"https://archive.org/metadata/{identifier}", timeout=20).json()
            mp4s = [f for f in (meta.get("files") or []) if (f.get("name") or "").lower().endswith(".mp4")]
            if not mp4s: continue
            url = f"https://archive.org/download/{identifier}/{mp4s[0]['name']}"
            raw = os.path.join(settings.output_dir, f"{_safe_name(tag)}_ia_raw.mp4")
            final = os.path.join(settings.output_dir, f"{_safe_name(tag)}_ia.mp4")
            if media.download(url, raw, timeout=240):
                return _trim_to_916(raw, final, dur)
    except Exception as e:
        logger.warning(f"archive failed → next source ({e})")
    return None

def image_motion(query, tag, dur=8):
    img = os.path.join(settings.output_dir, f"{_safe_name(tag)}_img.jpg")
    out = os.path.join(settings.output_dir, f"{_safe_name(tag)}_img.mp4")
    ok = media.commons_image(query, img)
    if not ok: return None
    try: return kenburns(img, out, dur)
    except Exception as e:
        logger.warning(f"kenburns failed: {e}")
        return None

def get_clip(query, tag, dur=8, article_link=None):
    os.makedirs(settings.output_dir, exist_ok=True)
    if article_link:
        try:
            from . import scraper
            embedded = scraper.embedded_videos(article_link)
            path = os.path.join(settings.output_dir, f"{_safe_name(tag)}_embed.mp4")
            clip = scraper.clip_from_urls(embedded, path, dur)
            if clip: return clip
        except Exception as e:
            logger.warning(f"article embedded clip failed → next source ({e})")
    clip = archive_clip(query, tag, dur)
    if clip: return clip
    clip = image_motion(query, tag, dur)
    if clip: return clip
    clip = viral_clip(query, tag, dur)
    if clip: return clip
    return None

def get_image(query, path):
    return media.commons_image(query or "news", path)