import asyncio, os
import edge_tts
from loguru import logger
from .config import settings

def _get_voice(text: str) -> str:
    if settings.narration_lang == "hi" or any("\u0900" <= c <= "\u097f" for c in text):
        return "hi-IN-MadhurNeural"
    return settings.tts_voice or "en-IN-PrabhatNeural"

async def _synth(text: str, path: str):
    timings = []
    voice = _get_voice(text)
    for v in [voice, "hi-IN-MadhurNeural", "en-IN-PrabhatNeural"]:
        try:
            timings.clear()
            comm = edge_tts.Communicate(text, v, rate="+8%")
            with open(path, "wb") as f:
                async for ch in comm.stream():
                    if ch["type"] == "audio":
                        f.write(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        timings.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return timings
        except Exception as e:
            logger.warning(f"TTS synth with voice '{v}' failed: {e}")
    return timings

def speak(text: str, tag: str):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, f"vo_{tag}.mp3")
    w = asyncio.run(_synth(text, mp3))
    return {"mp3": mp3, "words": w, "dur": (w[-1][2] if w else max(2.5, len(text) / 14.0)) + 0.5}