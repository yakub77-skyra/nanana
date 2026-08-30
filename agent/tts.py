import asyncio, os
import edge_tts
from .config import settings

async def _synth(text, path):
    timings = []
    comm = edge_tts.Communicate(text, settings.tts_voice, rate="+8%")
    with open(path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio": f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                timings.append((ch["text"], ch["offset"]/1e7, (ch["offset"]+ch["duration"])/1e7))
    return timings

def speak(text, tag):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, f"vo_{tag}.mp3")
    w = asyncio.run(_synth(text, mp3))
    return {"mp3": mp3, "words": w, "dur": (w[-1][2] if w else max(2.5, len(text)/14.0)) + 0.5}