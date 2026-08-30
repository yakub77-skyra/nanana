import asyncio, os
import feedparser
import instructor
import edge_tts
from openai import OpenAI
from loguru import logger

from .config import settings
from .schemas import Article, SelectedStory, StorySchema

llm = instructor.from_openai(OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key))

FEEDS = {
    "top":   "https://news.google.com/rss/headlines/section/topic/Top_stories?hl=en-IN&gl=IN&ceid=IN:en",
    "india": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
}

def fetch_news(state):
    arts, seen = [], set()
    for url in FEEDS.values():
        for e in feedparser.parse(url).entries[:15]:
            title = e.get("title", "")
            if not title or title in seen: continue
            seen.add(title)
            src = e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else ""
            arts.append(Article(title=title, link=e.link, source=src).model_dump())
    logger.info(f"📰 Fetched {len(arts)} fresh articles")
    return {"articles": arts}

def select_story(state):
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in enumerate(state["articles"]))
    resp = llm.chat.completions.create(
        model=settings.llm_model, response_model=SelectedStory, max_retries=3,
        messages=[{"role": "user", "content":
            "You are the viral editor of an Indian news Instagram page (style: @indiainlast24hr). "
            "Pick the ONE story with highest viral potential today (disaster/politics/crime/money/emotion). "
            f"Feed:\n{listing}"}])
    logger.success(f"🎯 Selected: {state['articles'][resp.article_index]['title']}")
    return {"selected": resp.model_dump()}

def extract_schema(state):
    a = state["articles"][state["selected"]["article_index"]]
    others = "\n".join(f"- {t['title']}" for t in state["articles"][:6] if t is not a)
    resp = llm.chat.completions.create(
        model=settings.llm_model, response_model=StorySchema,
        messages=[{"role": "user", "content": f"""You are the editor of @indiainlast24hr-style reel.
STORY: {a['title']} ({a['source']})
Build 6-9 scenes in order:
1) map scene (country, pin location, overlay_text hook, narration = hook line)
2-5) mix of clip (clip_query for footage search, stat_text like '3000+ MISSING', red_circle when dramatic), article (masthead+headline = source headline, narration = headline verbatim), quote (quote_text+person)
6+) 1-2 breaking scenes from OTHER headlines below (breaking_headline, breaking_sub, breaking_image_query; narration = headline)
Other headlines today:\n{others}
Also write caption + 8 hashtags."""}])
    return {"schema": resp.model_dump(), "article": a}

def render_scenes(state):
    from . import editor
    segs = [editor.render_scene(Scene(**s), i) for i, s in enumerate(state["schema"]["scenes"])]
    segs.append(fx_outro())
    return {"segments": segs}

def fx_outro():
    from .fx import outro_video
    return outro_video()

def assemble(state):
    from . import editor
    import os
    final = os.path.join(settings.output_dir, "reel_final.mp4")
    editor.assemble(state["segments"], final)
    return {"final": final}

def publish(state):
    from . import publisher
    publisher.publish(state["final"], state["schema"].get("caption", ""), state["schema"].get("hashtags", []))
    return {}

async def _tts(text: str, mp3: str):
    timings = []
    comm = edge_tts.Communicate(text, settings.tts_voice, rate="+8%")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                timings.append((chunk["text"], chunk["offset"] / 1e7,
                                (chunk["offset"] + chunk["duration"]) / 1e7))
    return timings

def synthesize_voice(state):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, "voice.mp3")
    timings = asyncio.run(_tts(state["schema"]["narration"], mp3))
    logger.info(f"🎙️ Voiceover ready ({len(timings)} word timestamps)")
    return {"voice": {"mp3": mp3, "words": timings}}
