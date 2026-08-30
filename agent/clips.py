import os, subprocess
from urllib.parse import quote
import httpx, imageio_ffmpeg as ioff
from loguru import logger
from .config import settings

FF = ioff.get_ffmpeg_exe()

def normalize(src, out, dur):
    cmd = [FF, "-y", "-i", src, "-t", f"{dur:.2f}",
           "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=30",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", out]
    subprocess.run(cmd, check=True, capture_output=True); return out

def ai_image(prompt, path):
    r = httpx.get(f"https://image.pollinations.ai/prompt/{quote(prompt)}?width=1080&height=1350&nologo=true", timeout=90)
    open(path, "wb").write(r.content); return path

def kenburns(img, out, dur):
    cmd = [FF, "-y", "-loop", "1", "-i", img,
           "-vf", f"scale=1400:-2,zoompan=z='min(zoom+0.0018,1.35)':d={int(dur*30)}:s=1080x1920:fps=30",
           "-t", f"{dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, check=True, capture_output=True); return out

def stock_clip(query, path):
    if not settings.pexels_api_key: return None
    r = httpx.get("https://api.pexels.com/videos/search",
                  params={"query": query, "per_page": 3, "orientation": "portrait"},
                  headers={"Authorization": settings.pexels_api_key}, timeout=30)
    for v in r.json().get("video_files", []):
        if v.get("width", 0) >= 720:
            open(path, "wb").write(httpx.get(v["link"], timeout=120).content); return path
    return None

def viral_clip(query, path):
    """Real 5-8s clips (fair-use snippet policy). Auto-falls-through on any failure."""
    if not settings.allow_viral_clips: return None
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as y:
            info = y.extract_info(f"ytsearch3:{query}")
        ent = next((e for e in info["entries"] if e and (e.get("duration") or 999) <= 120), None)
        if not ent: return None
        with yt_dlp.YoutubeDL({"quiet": True, "format": "best[ext=mp4]/best", "outtmpl": path,
                               "download_ranges": lambda i, y: [{"start_time": 5, "end_time": 13}]}) as y:
            y.download([ent["webpage_url"]])
        return path if os.path.exists(path) else None
    except Exception as e:
        logger.warning(f"viral clip failed → fallback ({e})"); return None

def get_clip(query, tag, dur):
    base = os.path.join(settings.output_dir, f"clip_{tag}")
    for fn in (stock_clip, viral_clip):
        p = fn(query, base + "_src.mp4")
        if p: return normalize(p, base + ".mp4", dur)
    img = ai_image(f"photojournalistic news photo, realistic: {query}", base + ".jpg")
    return kenburns(img, base + ".mp4", dur)