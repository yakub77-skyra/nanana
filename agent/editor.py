
import os, subprocess, json, re, math, random, textwrap, time
from pathlib import Path
from typing import List, Optional

import httpx
from playwright.sync_api import sync_playwright

from . import fx, media, scraper, tts
from .config import settings
from .schemas import Scene, Script

RAW = Path(settings.output_dir).resolve() / "raw"
OUT = Path(settings.output_dir).resolve() / "out"

# ------------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------------
def _ffmpeg(*args, check=True, **kw):
    return subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True, check=check, **kw)

def _ffprobe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration,r_frame_rate,width,height",
         "-of", "json", str(path)], capture_output=True, text=True
    )
    return json.loads(r.stdout) if r.returncode == 0 else {}

def _dur(path):
    info = _ffprobe(path)
    streams = info.get("streams", [])
    if streams:
        return float(streams[0].get("duration", 0))
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip()) if r.returncode == 0 else 0

def _fps(path):
    info = _ffprobe(path)
    streams = info.get("streams", [])
    if not streams:
        return 30
    rate = streams[0].get("r_frame_rate", "30/1")
    num, den = map(int, rate.split("/"))
    return num / den if den else 30

def _polish(path, fade_in=0.8, fade_out=0.8):
    d = _dur(path)
    if d <= 0:
        return path
    fi = min(fade_in, d * 0.15)
    fo = min(fade_out, d * 0.15)
    tmp = str(path) + "_polished.mp4"
    _ffmpeg("-i", str(path), "-vf", f"fade=t=in:st=0:d={fi},fade=t=out:st={max(0,d-fo)}:d={fo}",
            "-c:a", "copy", tmp, check=False)
    if os.path.exists(tmp):
        os.replace(tmp, str(path))
    return path

def _get_photo_b64(scene: Scene, img_path: Path):
    q = scene.clip_query or scene.breaking_image_query or scene.breaking_headline or "news"
    ok = media.download(scene.image_url, img_path) if scene.image_url else None
    if not ok and scene.article_link:
        ok = media.download(scraper.main_image_url(scene.article_link), img_path)
    if not ok:
        ok = media.commons_image(q, img_path)
    if ok and img_path.exists():
        return fx._b64(img_path)
    return ""

# ------------------------------------------------------------------
# RENDER SINGLE SCENE
# ------------------------------------------------------------------
def render_scene(scene: Scene, idx: int, tmp_dir: Path) -> Optional[Path]:
    name = f"scene_{idx:02d}_{scene.type}"
    out_path = tmp_dir / f"{name}.mp4"
    
    # ---- INTRO MARQUEE ----
    if scene.type == "intro_marquee":
        html = fx.intro_marquee_html(scene.text or scene.headline or "INDIA NEWS", scene.duration, theme=scene.theme)
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.3, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- MAP INTRO ----
    if scene.type == "map_intro":
        html = fx.map_intro_html(
            scene.country or "India",
            scene.overlay_text or scene.headline or "INDIA NEWS",
            scene.duration,
            theme=scene.theme,
            topic_img=scene.topic_img_path,
            pin=scene.pin
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- NEWS FRAME (numbered headline) ----
    if scene.type == "news_frame":
        img = tmp_dir / f"{name}_photo.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.news_frame_html(
            scene.number or 1,
            scene.headline or scene.breaking_headline or "HEADLINE",
            b64,
            scene.location or scene.country or "INDIA",
            scene.duration,
            theme=scene.theme
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- ARTICLE CARD ----
    if scene.type == "article_card":
        img = tmp_dir / f"{name}_bg.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.article_card_html(
            scene.masthead,
            scene.headline,
            scene.category,
            scene.date_str,
            b64,
            scene.duration,
            source_color=scene.source_color or "#c00"
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- LOCATION HIGHLIGHT ----
    if scene.type == "location_highlight":
        img = tmp_dir / f"{name}_photo.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.location_highlight_html(
            scene.country or "India",
            scene.location,
            b64,
            scene.overlay_text or scene.headline,
            scene.duration,
            theme=scene.theme
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- DISASTER DRAMATIC ----
    if scene.type == "disaster_dramatic":
        img = tmp_dir / f"{name}_footage.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.disaster_dramatic_html(
            scene.headline,
            scene.sub_text,
            b64,
            scene.duration
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.3, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- FOOTAGE HIGHLIGHT ----
    if scene.type == "footage_highlight":
        img = tmp_dir / f"{name}_footage.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.footage_highlight_html(
            b64,
            circle_x=scene.circle_x or 540,
            circle_y=scene.circle_y or 960,
            circle_r=scene.circle_radius or 200,
            label_text=scene.label_text or "",
            dur=scene.duration
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.3, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- BREAKING CARD ----
    if scene.type == "breaking_card":
        img = tmp_dir / f"{name}_img.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.breaking_card_html(
            scene.headline,
            scene.sub_text,
            b64,
            scene.duration,
            source=scene.source or ""
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.3, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- QUOTE CARD ----
    if scene.type == "quote_card":
        html = fx.quote_card_html(
            scene.quote_text or scene.text,
            scene.quote_person or scene.headline,
            scene.duration,
            theme=scene.theme
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- STAT OVERLAY ----
    if scene.type == "stat_overlay":
        img = tmp_dir / f"{name}_bg.jpg"
        b64 = _get_photo_b64(scene, img)
        html = fx.stat_overlay_html(
            scene.stat_text,
            scene.stat_label,
            b64,
            scene.duration,
            theme=scene.theme
        )
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.5)
        os.replace(raw, out_path)
        return out_path
    
    # ---- OUTRO ----
    if scene.type == "outro":
        html = fx.outro_html(scene.duration)
        raw = fx.record_html(html, scene.duration, name)
        _polish(raw, fade_in=0.5, fade_out=0.8)
        os.replace(raw, out_path)
        return out_path
    
    return None

# ------------------------------------------------------------------
# ASSEMBLE
# ------------------------------------------------------------------
def assemble(clips: List[Path], out_path: Path, music_path: Optional[Path] = None, target_duration: Optional[float] = None):
    if not clips:
        return None
    
    concat_list = out_path.parent / "concat_list.txt"
    with open(concat_list, "w") as f:
        for c in clips:
            f.write(f"file '{c.resolve()}'\n")
    
    tmp_vid = str(out_path) + "_tmp.mp4"
    _ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", tmp_vid, check=False)
    
    if not os.path.exists(tmp_vid):
        return None
    
    vid_dur = _dur(tmp_vid)
    
    # Add music if available
    if music_path and music_path.exists():
        music_dur = _dur(music_path)
        loops = math.ceil(vid_dur / music_dur) if music_dur > 0 else 1
        music_looped = str(out_path.parent / "music_looped.mp3")
        _ffmpeg("-stream_loop", str(loops - 1), "-i", str(music_path), "-t", str(vid_dur),
                "-c:a", "libmp3lame", "-q:a", "2", music_looped, check=False)
        
        final_tmp = str(out_path) + "_final.mp4"
        _ffmpeg("-i", tmp_vid, "-i", music_looped, "-shortest",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-af", "volume=0.25", final_tmp, check=False)
        
        if os.path.exists(final_tmp):
            os.replace(final_tmp, str(out_path))
        if os.path.exists(music_looped):
            os.remove(music_looped)
    else:
        os.replace(tmp_vid, str(out_path))
    
    if os.path.exists(concat_list):
        os.remove(concat_list)
    if os.path.exists(tmp_vid):
        os.remove(tmp_vid)
    
    return out_path

# ------------------------------------------------------------------
# BUILD
# ------------------------------------------------------------------
def build(script: Script, out_name: str = "reel") -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp_dir = RAW / f"build_{out_name}_{int(time.time())}"
    tmp_dir.mkdir(exist_ok=True)
    
    clips: List[Path] = []
    
    for idx, scene in enumerate(script.scenes):
        print(f"  [editor] Rendering scene {idx+1}/{len(script.scenes)}: {scene.type}")
        path = render_scene(scene, idx, tmp_dir)
        if path and path.exists():
            clips.append(path)
    
    if not clips:
        raise RuntimeError("No clips rendered")
    
    # Download music if specified
    music_path = None
    if script.music_query:
        music_path = tmp_dir / "bgm.mp3"
        media.download(script.music_query, music_path)
        if not music_path.exists():
            music_path = None
    
    out_path = OUT / f"{out_name}.mp4"
    assemble(clips, out_path, music_path=music_path, target_duration=script.total_duration or None)
    
    return out_path
