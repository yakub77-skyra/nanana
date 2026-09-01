import asyncio, os, re, subprocess
import edge_tts
import httpx
import imageio_ffmpeg as ioff
from loguru import logger
from .config import settings

FF = ioff.get_ffmpeg_exe()

def _get_voice(text: str) -> str:
    if settings.narration_lang == "hi" or any("\u0900" <= c <= "\u097f" for c in text):
        return "hi-IN-MadhurNeural"
    return settings.tts_voice or "en-IN-PrabhatNeural"

def _probe_dur(mp3):
    try:
        probe = subprocess.run([FF, "-i", mp3], capture_output=True, text=True)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", probe.stderr)
        if m: return float(m.group(1))*3600 + float(m.group(2))*60 + float(m.group(3))
    except Exception:
        pass
    return None

def _uniform_timings(text, dur):
    """P6.5: even word sweep when no WordBoundary data → scenes never go silent."""
    words = text.split()
    if not words or dur <= 0: return []
    step = dur / len(words)
    return [(w, i*step, (i+1)*step) for i, w in enumerate(words)]

async def _synth_edge(text, path):
    timings = []
    voice = _get_voice(text)
    for v in [voice, "hi-IN-MadhurNeural", "hi-IN-SwaraNeural", "en-IN-PrabhatNeural"]:
        try:
            timings.clear()
            comm = edge_tts.Communicate(text, v, rate="+8%")
            with open(path, "wb") as f:
                async for ch in comm.stream():
                    if ch["type"] == "audio": f.write(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        timings.append((ch["text"], ch["offset"]/1e7, (ch["offset"]+ch["duration"])/1e7))
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return timings
        except Exception as e:
            logger.warning(f"TTS synth with voice '{v}' failed: {e}")
    return timings

def _synth_elevenlabs(text, path):
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
                   headers={"xi-api-key": settings.elevenlabs_api_key},
                   json={"text": text, "model_id": "eleven_multilingual_v2",
                         "voice_settings": {"stability": 0.45, "similarity_boost": 0.75}},
                   timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}")
    open(path, "wb").write(r.content)

def speak(text, tag):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, f"vo_{tag}.mp3")
    w = []
    if settings.elevenlabs_api_key:
        try:
            _synth_elevenlabs(text, mp3)
            logger.info("🎙️ ElevenLabs voice used")
        except Exception as e:
            logger.warning(f"ElevenLabs failed → edge-tts ({e})")
            w = asyncio.run(_synth_edge(text, mp3))
    else:
        w = asyncio.run(_synth_edge(text, mp3))

    dur = (w[-1][2] + 0.5) if w else 4.0
    if not w:
        d = _probe_dur(mp3)
        if d: dur = d + 0.4
        w = _uniform_timings(text, dur)
    return {"mp3": mp3, "words": w, "dur": dur}

def speak_full(narrations, tag="full"):
    text = " ".join(n for n in narrations if n).strip() if isinstance(narrations, list) else (narrations or "")
    return speak(text, tag)