import os
import re
import subprocess
from pathlib import Path

import httpx
import imageio_ffmpeg as ioff
from loguru import logger

from .config import settings
from . import media

FF = ioff.get_ffmpeg_exe()


def _safe_name(s):
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s or "clip")
    return s[:60] or "clip"


def _terms(query):
    return [w.lower() for w in re.findall(r"[a-zA-Z]{4,}", query or "")]


def _looks_related(title, query):
    title_l = (title or "").lower()
    terms = _terms(query)
    if not terms:
        return True
    hits = sum(1 for t in terms if t in title_l)
    return hits >= min(2, len(terms))


def _trim_to_916(src, out, dur):
    """Normalize any real video to 1080x1920."""
    cmd = [
        FF, "-y",
        "-i", src,
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,fps=30",
        "-t", f"{dur:.2f}",
        "-an",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out if os.path.exists(out) else None


def kenburns(img, out, dur):
    """Turn a real image into motion video."""
    cmd = [
        FF, "-y",
        "-loop", "1",
        "-i", img,
        "-vf",
        f"scale=1400:-2,zoompan=z='min(zoom+0.0018,1.35)':"
        f"d={int(dur * 30)}:s=1080x1920:fps=30",
        "-t", f"{dur:.2f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        out,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def viral_clip(query, tag, dur=8):
    """
    Try YouTube search as a last-resort viral clip source.
    M016: retries with android player_client when CI gets bot-blocked.
    """
    if not settings.allow_viral_clips:
        return None

    try:
        import yt_dlp
    except Exception:
        return None

    raw = os.path.join(settings.output_dir, f"{_safe_name(tag)}_yt.%(ext)s")
    final = os.path.join(settings.output_dir, f"{_safe_name(tag)}_yt.mp4")
    search = f"ytsearch1:{query} news"

    try:
        opts = {
            "quiet": True,
            "format": "best[ext=mp4]/best",
            "outtmpl": raw,
            "noplaylist": True,
            "download_ranges": lambda info, ydl: [
                {"start_time": 5, "end_time": 5 + dur}
            ],
        }

        try:
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([search])
        except Exception:
            opts["extractor_args"] = {
                "youtube": {"player_client": ["android"]}
            }
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([search])

        candidates = list(Path(settings.output_dir).glob(f"{_safe_name(tag)}_yt.*"))
        candidates = [str(p) for p in candidates if p.suffix.lower() in {".mp4", ".webm", ".mkv"}]

        if not candidates:
            return None

        return _trim_to_916(candidates[0], final, dur)

    except Exception as e:
        logger.warning(f"viral clip failed → next source ({e})")
        return None


def archive_clip(query, tag, dur=8):
    """Try Internet Archive for real public-domain footage."""
    try:
        q = " ".join(_terms(query)[:5]) or "news"
        r = httpx.get(
            "https://archive.org/advancedsearch.php",
            timeout=20,
            params={
                "q": f'title:({q}) AND mediatype:(movies)',
                "fl[]": ["identifier", "title", "year"],
                "rows": 8,
                "page": 1,
                "output": "json",
            },
        )

        data = r.json()
        docs = ((data.get("response") or {}).get("docs") or [])

        docs = [
            d for d in docs
            if _looks_related(d.get("title", ""), query)
        ]

        for d in docs:
            identifier = d.get("identifier")
            if not identifier:
                continue

            meta = httpx.get(
                f"https://archive.org/metadata/{identifier}",
                timeout=20,
            ).json()

            files = meta.get("files") or []
            mp4s = [
                f for f in files
                if (f.get("name") or "").lower().endswith(".mp4")
            ]

            if not mp4s:
                continue

            name = mp4s[0]["name"]
            url = f"https://archive.org/download/{identifier}/{name}"

            raw = os.path.join(settings.output_dir, f"{_safe_name(tag)}_ia_raw.mp4")
            final = os.path.join(settings.output_dir, f"{_safe_name(tag)}_ia.mp4")

            if media.download(url, raw, timeout=240):
                return _trim_to_916(raw, final, dur)

    except Exception as e:
        logger.warning(f"archive failed → next source ({e})")

    return None


def image_motion(query, tag, dur=8):
    """Fallback: real Commons image with Ken Burns motion."""
    img = os.path.join(settings.output_dir, f"{_safe_name(tag)}_img.jpg")
    out = os.path.join(settings.output_dir, f"{_safe_name(tag)}_img.mp4")

    ok = media.commons_image(query, img)
    if not ok:
        return None

    try:
        return kenburns(img, out, dur)
    except Exception as e:
        logger.warning(f"kenburns failed: {e}")
        return None


def get_clip(query, tag, dur=8, article_link=None):
    """
    Clip source priority:
    1. Real embedded video from article.
    2. Viral/public video search.
    3. Internet Archive.
    4. Commons image motion.
    """
    os.makedirs(settings.output_dir, exist_ok=True)

    if article_link:
        try:
            from . import scraper

            embedded = scraper.embedded_videos(article_link)
            path = os.path.join(settings.output_dir, f"{_safe_name(tag)}_embed.mp4")
            clip = scraper.clip_from_urls(embedded, path, dur)
            if clip:
                return clip
        except Exception as e:
            logger.warning(f"article embedded clip failed → next source ({e})")

    clip = archive_clip(query, tag, dur)
    if clip:
        return clip

    clip = image_motion(query, tag, dur)
    if clip:
        return clip

    clip = viral_clip(query, tag, dur)
    if clip:
        return clip

    return None


def get_image(query, path):
    """Real image helper for breaking cards."""
    return media.commons_image(query or "news", path)