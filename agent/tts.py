import asyncio, os, re, subprocess
import edge_tts
import imageio_ffmpeg as ioff
from loguru import logger
from .config import settings

FF = ioff.get_ffmpeg_exe()

def _get_voice(text: str) -> str:
    if settings.narration_lang == "hi" or any("\u0900" <= c <= "\u097f" for c in text):
        return "hi-IN-MadhurNeural"
    return settings.tts_voice or "en-IN-PrabhatNeural"

async def _synth(text: str, path: str):
    timings = []
    voice = _get_voice(text)
    for v in [voice, "hi-IN-MadhurNeural", "hi-IN-SwaraNeural", "en-IN-PrabhatNeural"]:
        try:
            timings.clear()
            comm = edge_tts.Communicate(text, v, rate="+8%")
            with open(path, "wb") as f:
                async for ch in comm.stream():
                    if ch["type"] == "audio":
                        f.write(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        timings.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return timings
        except Exception as e:
            logger.warning(f"TTS synth with voice '{v}' failed: {e}")
    return timings

def speak(text: str, tag: str):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, f"vo_{tag}.mp3")
    w = asyncio.run(_synth(text, mp3))
    
    dur = 4.0
    if w and len(w) > 0:
        dur = w[-1][2] + 0.5
    elif os.path.exists(mp3) and os.path.getsize(mp3) > 0:
        try:
            probe = subprocess.run([FF, "-i", mp3], capture_output=True, text=True)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", probe.stderr)
            if m:
                dur = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3)) + 0.4
            else:
                dur = max(3.0, len(text) / 10.0)
        except Exception:
            dur = max(3.0, len(text) / 10.0)
            
    return {"mp3": mp3, "words": w, "dur": dur}

def speak_full(narrations, tag: str = "full"):
    if isinstance(narrations, list):
        text = " ".join(n for n in narrations if n).strip()
    else:
        text = narrations or ""
    return speak(text, tag)

