import os, subprocess, datetime
import httpx, imageio_ffmpeg as ioff
from loguru import logger
from . import media
from .config import settings

FF = ioff.get_ffmpeg_exe()

def normalize(src, out, dur):
    cmd = [FF, "-y", "-i", src, "-t", f"{dur:.2f}",
           "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=30",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", out]
    subprocess.run(cmd, check=True, capture_output=True); return out

def kenburns(img, out, dur):
    cmd = [FF, "-y", "-loop", "1", "-i", img,
           "-vf", f"scale=1400:-2,zoompan=z='min(zoom+0.0018,1.35)':d={int(dur*30)}:s=1080x1920:fps=30",
           "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True, capture_output=True); return out

def viral_clip(query, path):
    """REAL fresh news clips from YouTube — uploaded within last 60 days only."""
    if not settings.allow_viral_clips: return None
    try:
        import yt_dlp
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=60)).strftime("%Y%m%d")
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as y:
            info = y.extract_info(f"ytsearch5:{query} news", download=False)
        ent = next((e for e in (info.get("entries") or [])
                    if e and (e.get("upload_date") or "99999999") >= cutoff
                    and (e.get("duration") or 90) <= 120), None)
        if not ent: return None
        url = ent.get("url") or ent.get("webpage_url")
        with yt_dlp.YoutubeDL({"quiet": True, "format": "best[ext=mp4]/best", "outtmpl": path,
                               "download_ranges": lambda i, y: [{"start_time": 5, "end_time": 13}]}) as y:
            y.download([url])
        return path if os.path.exists(path) else None
    except Exception as e:
        logger.warning(f"viral clip failed → next source ({e})")
        return None

def archive_clip(query, path):
    """REAL archive footage — 2015+ only, title must actually mention the topic."""
    try:
        r = httpx.get("https://archive.org/advancedsearch.php", timeout=20, params={
            "q": f"({query}) AND mediatype:(movies) AND year:[2015 TO 2026]",
            "fl[]": "identifier,title", "rows": 5, "page": 1, "output": "json"}).json()
        words = set(query.lower().split())
        for d in (r.get("response") or {}).get("docs") or []:
            title = (d.get("title") or "").lower()
            if not (words & set(title.split())): continue      # no more Pathé/Zoom junk
            m = httpx.get(f"https://archive.org/metadata/{d['identifier']}", timeout=20).json()
            f = next((x for x in m.get("files", [])
                      if x["name"].lower().endswith(".mp4")
                      and float(x.get("size", 1e12)) < 300_000_000), None)
            if f and media.download(f"https://archive.org/download/{d['identifier']}/{f['name']}", path, 240):
                return path
    except Exception as e:
        logger.warning(f"archive failed → next source ({e})")
    return None

def get_image(query, path):
    """REAL photos only — Wikimedia Commons press/CC photos. NO stock, NO AI."""
    return media.commons_image(query, path)

def get_clip(query, tag, dur):
    base = os.path.join(settings.output_dir, f"clip_{tag}")
    p = viral_clip(query, base + "_v.mp4")            # 1. fresh REAL news clip
    if p: return normalize(p, base + ".mp4", dur)
    p = archive_clip(query, base + "_ia.mp4")         # 2. REAL archive footage (filtered)
    if p: return normalize(p, base + ".mp4", dur)
    img = get_image(query, base + ".jpg")             # 3. Ken Burns on a REAL photo
    if img: return kenburns(img, base + ".mp4", dur)
    return None                                       # → scene skipped by safety net