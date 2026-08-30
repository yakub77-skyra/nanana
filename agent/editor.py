import os, subprocess
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg as ioff
from loguru import logger
from . import fx, tts, clips
from .config import settings
from .renderer import CARD  # Phase-1 card
from .schemas import Scene

FF = ioff.get_ffmpeg_exe()

def _seg_mux(visual_webm, vo, out, dur):
    cmd = [FF, "-y", "-i", visual_webm]
    if vo: cmd += ["-i", vo["mp3"]]
    else: cmd += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo"]
    cmd += ["-t", f"{dur:.2f}", "-vf", "scale=1080:1920,fps=30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", out]
    subprocess.run(cmd, check=True, capture_output=True)

def _overlay_png(scene, path):
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    if scene.red_circle:
        d.ellipse([240, 660, 840, 1260], outline=(220, 0, 0, 255), width=14)
    if scene.stat_text:
        try: f = ImageFont.truetype("arial.ttf", 84)
        except Exception: f = ImageFont.load_default(84)
        d.text((540, 1560), scene.stat_text.upper(), font=f, fill=(255, 255, 255, 255),
               stroke_width=6, stroke_fill=(0, 0, 0, 255), anchor="mm")
    img.save(path)

def render_scene(scene: Scene, i: int) -> str:
    vo = tts.speak(scene.narration, f"s{i}") if scene.narration else None
    dur = vo["dur"] if vo else 4.0
    out = os.path.join(settings.output_dir, f"seg_{i}.mp4")
    if scene.type == "map":
        webm = fx.record_html(fx.map_html(scene.country or "India", scene.pin, scene.overlay_text, dur), dur, f"map{i}")
        _seg_mux(webm, vo, out, dur)
    elif scene.type == "clip":
        clip = clips.get_clip(scene.clip_query or "news", f"s{i}", dur)
        if scene.red_circle or scene.stat_text:
            ov = os.path.join(settings.output_dir, f"ov_{i}.png"); _overlay_png(scene, ov)
            tmp = os.path.join(settings.output_dir, f"clipov_{i}.mp4")
            subprocess.run([FF, "-y", "-i", clip, "-i", ov, "-filter_complex",
                            "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", tmp],
                           check=True, capture_output=True)
            clip = tmp
        _seg_mux(clip, vo, out, dur)
    elif scene.type == "article":
        words = (scene.headline or "").split()
        delays = [w[1] + .3 for w in vo["words"]][:len(words)] or [j * .4 for j in range(len(words))]
        sp = "".join(f'<span class="w"><i style="animation-delay:{d:.2f}s"></i><b>{w}</b></span>' for w, d in zip(words, delays))
        page = (CARD.replace("__HANDLE__", settings.ig_handle).replace("__MASTHEAD__", (scene.masthead or "THE TIMES OF INDIA").upper())
                .replace("__HEADLINE__", sp).replace("__META__", scene.masthead or "").replace("__BIG__", scene.stat_text or ""))
        _seg_mux(fx.record_html(page, dur, f"art{i}"), vo, out, dur)
    elif scene.type == "quote":
        _seg_mux(fx.record_html(fx.quote_html(scene.quote_text, scene.person or "", vo["words"], dur), dur, f"q{i}"), vo, out, dur)
    elif scene.type == "breaking":
        img = clips.ai_image(f"photojournalistic news photo: {scene.breaking_image_query or scene.breaking_headline}",
                             os.path.join(settings.output_dir, f"br_{i}.jpg"))
        _seg_mux(fx.record_html(fx.breaking_html(scene.breaking_headline, scene.breaking_sub, img, dur), dur, f"b{i}"), vo, out, dur)
    logger.success(f"🎞️ Scene {i} ({scene.type}) rendered")
    return out

def assemble(segments, final):
    listf = os.path.join(settings.output_dir, "segs.txt")
    with open(listf, "w") as f:
        f.write("\n".join(f"file '{s}'" for s in segments))
    joined = os.path.join(settings.output_dir, "joined.mp4")
    subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", listf, "-c", "copy", joined],
                   check=True, capture_output=True)
    music = os.path.join("assets", "music.mp3")
    cmd = [FF, "-y", "-i", joined]
    if os.path.exists(music):
        cmd += ["-i", music, "-filter_complex", "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "0:a"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", final]
    subprocess.run(cmd, check=True, capture_output=True)
    logger.success(f"✅ FULL REEL: {final}")