import datetime
import asyncio
import os
import json

import feedparser
import instructor
import edge_tts
import httpx
from openai import OpenAI
from loguru import logger

from .config import settings
from .schemas import Article, SelectedStory, StorySchema, Scene, RoundupSchema, RoundupScene, CommentReply

llm = instructor.from_openai(OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key))

# ------------------------------------------------------------------
# FREE-MODEL FAILOVER LOGIC
# ------------------------------------------------------------------
def _live_free_models():
    """Ask OpenRouter which models are $0 TODAY (lineup rotates)."""
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20).json()
        return [m["id"] for m in r.get("data", [])
                if m.get("pricing", {}).get("prompt") == "0"
                and m.get("pricing", {}).get("completion") == "0"]
    except Exception:
        return []

def _model_chain():
    pref = [m.strip() for m in settings.llm_fallbacks.split(",") if m.strip()]
    if settings.llm_model:
        pref = [settings.llm_model] + pref
    live = _live_free_models()
    chain = [m for m in pref if m in live or m.endswith(":free")]
    chain += [m for m in live if m not in chain][:3]   # top-up with any live free models
    return chain or pref

def llm_create(prompt, response_model=None):
    """LLM call with automatic free-model failover."""
    last: Exception = RuntimeError("No free models available — check OpenRouter or your llm_fallbacks config")
    for model in _model_chain():
        try:
            if response_model:
                return llm.chat.completions.create(model=model, response_model=response_model,
                                                   max_retries=2,
                                                   messages=[{"role": "user", "content": prompt}])
            r = llm.chat.completions.create(model=model, max_retries=2,
                                            messages=[{"role": "user", "content": prompt}])
            return r.choices[0].message.content
        except Exception as e:
            last = e
            logger.warning(f"⚡ {model} failed → trying next free model")
    raise last

FEEDS = {
    "top":   "https://news.google.com/rss/headlines/section/topic/Top_stories?hl=en-IN&gl=IN&ceid=IN:en",
    "india": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
}

ZERNIO = "https://zernio.com/api/v1"
HIST, ANA = "history.json", "analytics.json"

def _load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

# ------------------------------------------------------------------
# 1. FETCH
# ------------------------------------------------------------------
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

# ------------------------------------------------------------------
# 2. LEARN (reads last 12 reels from Zernio → agent imitates winners)
# ------------------------------------------------------------------
def learn(state):
    if not settings.zernio_api_key:
        logger.info("📊 Zernio not connected — skipping learn loop")
        return {}
    try:
        r = httpx.get(f"{ZERNIO}/posts",
                      params={"limit": 12},
                      headers={"Authorization": f"Bearer {settings.zernio_api_key}"},
                      timeout=30).json()
        rows = r.get("posts", r.get("data", []))
        json.dump(rows, open(ANA, "w", encoding="utf-8"), indent=1, default=str)
        logger.info(f"📊 Insights saved: {len(rows)} recent reels")
    except Exception as e:
        logger.warning(f"insights skipped: {e}")
    return {}

# ------------------------------------------------------------------
# 3. SELECT STORY (avoids repeats + imitates past winners)
# ------------------------------------------------------------------
def select_story(state):
    hist = _load(HIST).get("recent", [])
    ana  = _load(ANA)
    winners = "\n".join(f"- {m.get('content','')[:80]} → {m.get('likeCount', m.get('playCount', 0))} plays"
                        for m in ana[:3]) or "none yet"
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}"
                        for i, a in enumerate(state["articles"])
                        if a["title"] not in hist)
    
    prompt = ("You are the viral editor of an Indian news Instagram page (style: @indiainlast24hr). "
              "Pick the ONE story with highest viral potential today (disaster/politics/crime/money/emotion). "
              "Do NOT repeat recently covered stories.\n"
              f"Your past WINNING reels (imitate their hook style):\n{winners}\n"
              f"Feed:\n{listing}")
              
    resp = llm_create(prompt, SelectedStory)
    
    h = _load(HIST)
    h["recent"] = (h.get("recent", []) + [state["articles"][resp.article_index]["title"]])[-10:]
    json.dump(h, open(HIST, "w", encoding="utf-8"), ensure_ascii=False)
    logger.success(f"🎯 Selected: {state['articles'][resp.article_index]['title']}")
    return {"selected": resp.model_dump()}

# ------------------------------------------------------------------
# 4. EXTRACT SCHEMA (Hindi VO + English on-screen + 80s cap for Reels)
# ------------------------------------------------------------------
def extract_schema(state):
    a = state["articles"][state["selected"]["article_index"]]
    others = "\n".join(f"- {t['title']}" for t in state["articles"][:6] if t is not a)
    lang_hint = ("narration lines MUST be in simple spoken Hindi, Devanagari script. "
                 if settings.narration_lang == "hi"
                 else "narration lines MUST be in crisp English. ")
                 
    prompt = f"""You are the editor of @indiainlast24hr-style reel.
STORY: {a['title']} ({a['source']})
{lang_hint}All ON-SCREEN text (overlay_text, stat_text, big_text, breaking_headline) stays ENGLISH CAPS.
TOTAL narration across ALL scenes must stay under 80 seconds (≈180 Hindi words or ≈140 English words) so the reel stays under 90s.
Build 6-9 scenes in order:
1) map scene (country, pin location, overlay_text hook, narration = hook line)
2-5) mix of clip (clip_query for footage search, stat_text like '3000+ MISSING', red_circle when dramatic),
     article (masthead+headline = source headline, narration = headline verbatim),
     quote (quote_text+person)
6+) 1-2 breaking scenes from OTHER headlines below (breaking_headline, breaking_sub, breaking_image_query; narration = headline)
Other headlines today:\n{others}
Also write caption + 8 hashtags.

CRITICAL VISUAL RULES:
- clip_query and breaking_image_query must be GENERIC searchable footage keywords (e.g. "flood river rescue boat", "parliament building"), NEVER proper nouns or specific names.
- Never use graphic, gory, or disturbing imagery descriptions."""

    resp = llm_create(prompt, StorySchema)
    return {"schema": resp.model_dump(), "article": a}

# ------------------------------------------------------------------
# 5. RENDER SCENES (each scene → TTS + visual → segment file)
# ------------------------------------------------------------------
def render_scenes(state):
    from . import editor, fx, media
    scenes = [Scene(**s) for s in state["schema"]["scenes"]]

    # Attach REAL article photos (match scene → article → og:image)
    for sc in scenes:
        if sc.type in ("article", "breaking") and not sc.image_url:
            target = (sc.headline or sc.breaking_headline or "").lower()
            hit = next((a for a in state["articles"]
                        if sum(w in a["title"].lower() for w in target.split()[:5]) >= 2), None)
            if hit:
                sc.image_url = media.og_image(hit["link"])
                logger.info(f"🖼️ Real article photo attached: {hit['source']}")

    # ONE human-like voice take for the whole reel (no more breaks)
    take = tts.speak_full([sc.narration for sc in scenes], "full")
    segs = editor.render_all(scenes, take)
    segs.append(fx.outro_video())
    return {"segments": segs}

# ------------------------------------------------------------------
# 6. ASSEMBLE (concat segments + music → final reel)
# ------------------------------------------------------------------
def assemble(state):
    from . import editor
    final = os.path.join(settings.output_dir, "reel_final.mp4")
    editor.assemble(state["segments"], final)
    return {"final": final}

# ------------------------------------------------------------------
# 7. PUBLISH (via Zernio)
# ------------------------------------------------------------------
def publish(state):
    from . import publisher
    publisher.publish(state["final"],
                      state["schema"].get("caption", ""),
                      state["schema"].get("hashtags", []))
    return {}

# ------------------------------------------------------------------
# (Phase-1 legacy TTS kept for reference; Phase 2 uses per-scene TTS in editor.py)
# ------------------------------------------------------------------
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
    """Legacy hook kept for backward compatibility.
    Phase 2 moved TTS into editor.render_scene so every scene gets its own voice."""
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, "voice.mp3")
    timings = asyncio.run(_tts(state["schema"]["narration"], mp3))
    logger.info(f"🎙️ Legacy voiceover ready ({len(timings)} word timestamps)")
    return {"voice": {"mp3": mp3, "words": timings}}

# ------------------------------------------------------------------
# 8. PHASE 4: SELECT FORMAT
# ------------------------------------------------------------------
def select_format(state):
    """Decides whether to make a Deep Dive or Top-8 Roundup based on the time of day (IST)."""
    # Convert UTC to IST (UTC+5:30)
    ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    hour = ist_now.hour
    
    # Evening prime time (18:00 to 21:00 IST) gets the fast-paced Roundup. 
    # Morning/Afternoon gets the Deep Dive story.
    fmt = "roundup" if 18 <= hour < 21 else "deep_dive"
    logger.info(f"⏰ Time is {hour}:00 IST → Format chosen: {fmt.upper()}")
    return {"reel_format": fmt}

# ------------------------------------------------------------------
# 9. PHASE 4: EXTRACT ROUNDUP
# ------------------------------------------------------------------
def extract_roundup(state):
    """Generates the Top-8 Headlines format."""
    # Pick top 8 unique headlines from the feed
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in enumerate(state["articles"][:15]))
    
    lang_hint = "simple spoken Hindi" if settings.narration_lang == "hi" else "crisp English"
    
    prompt = f"""You are the editor of @indiainlast24hr. Create a fast-paced "Top 8 Headlines" reel.
Intro: A catchy hook in {lang_hint}.
Scenes: Pick the 8 most important/viral DISTINCT stories from the feed below. 
Each scene needs a short ENGLISH CAPS headline, a 1-sentence {lang_hint} narration, and an image query.
Feed:\n{listing}
Also write caption + 8 hashtags.

CRITICAL VISUAL RULES:
- image_query must be GENERIC searchable footage keywords (e.g. "stock market crash", "cricket stadium crowd"), NEVER proper nouns or specific names.
- Never use graphic, gory, or disturbing imagery descriptions."""

    resp = llm_create(prompt, RoundupSchema)
    
    # Convert RoundupScenes into standard 'breaking' scenes for the renderer
    scenes = []
    # Intro scene
    scenes.append(Scene(type="breaking", breaking_headline="INDIA IN LAST 24 HOURS", 
                        breaking_sub="TOP 8 HEADLINES", breaking_image_query="india news studio", 
                        narration=resp.intro_narration).model_dump())
    
    # 8 Headline scenes
    for i, item in enumerate(resp.scenes):
        scenes.append(Scene(type="breaking", breaking_headline=item.headline, 
                            breaking_sub=f"#{i+1}", breaking_image_query=item.image_query, 
                            narration=item.narration).model_dump())
                            
    return {"schema": {"scenes": scenes, "caption": resp.caption, "hashtags": resp.hashtags}, 
            "article": state["articles"][0]}

# ------------------------------------------------------------------
# 10. PHASE 4: AUTO REPLY TO COMMENTS
# ------------------------------------------------------------------
def reply_comments(state):
    """Reads recent comments on Zernio and auto-replies to boost engagement."""
    if not settings.zernio_api_key: return {}
    try:
        # 1. Fetch recent posts to get their IDs
        posts = httpx.get(f"{ZERNIO}/posts", params={"limit": 3}, 
                          headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        
        post_ids = [p.get("id") or p.get("_id") for p in posts.get("posts", []) if p.get("platform") == "instagram"]
        if not post_ids: return {}

        # 2. Fetch unread/recent comments
        comments_res = httpx.get(f"{ZERNIO}/comments", params={"postId": post_ids[0], "limit": 5},
                                 headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        
        comments = comments_res.get("comments", comments_res.get("data", []))
        replied = 0
        
        for c in comments:
            c_id = c.get("id") or c.get("_id")
            c_text = c.get("text", c.get("message", ""))
            c_user = c.get("user", {}).get("name", "User")
            
            # Skip if already replied or if it's our own comment
            if c.get("isRead") or c.get("isOwner") or replied >= 2: continue 
            
            # 3. LLM generates a friendly, engaging reply
            reply_resp = llm_create(
                f"Write a 1-sentence friendly reply to this Instagram comment from {c_user}: '{c_text}'. Ask a question back to boost engagement. Reply ONLY with the text.",
                CommentReply
            )
            
            reply_text = reply_resp.text if hasattr(reply_resp, 'text') else str(reply_resp)
            
            # 4. Post reply via Zernio
            httpx.post(f"{ZERNIO}/comments/{c_id}/reply",
                       headers={"Authorization": f"Bearer {settings.zernio_api_key}"},
                       json={"text": reply_text}, timeout=30)
            replied += 1
            logger.info(f"💬 Replied to {c_user}")
            
    except Exception as e:
        logger.warning(f"comment reply loop skipped: {e}")
    return {}