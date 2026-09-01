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

try:
    import googlenewsdecoder
except Exception:
    googlenewsdecoder = None

from .config import settings
from .schemas import Article, SelectedStory, StorySchema, Scene, RoundupSchema, RoundupScene, CommentReply

llm = instructor.from_openai(OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key))

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ------------------------------------------------------------------
# FREE-MODEL FAILOVER
# ------------------------------------------------------------------
def _live_free_models():
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
    chain += [m for m in live if m not in chain][:3]
    return chain or pref

def llm_create(prompt, response_model=None):
    last: Exception = RuntimeError("No free models available — check OpenRouter or llm_fallbacks")
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
            logger.warning(f"⚡ {model} failed → next free model")
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

def _real_url(link):
    if "news.google.com" not in link:
        return link
    if googlenewsdecoder:
        try:
            res = googlenewsdecoder.gnewsdecoder(link)
            if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
                return res["decoded_url"]
        except Exception:
            pass
    try:
        r = httpx.get(link, timeout=10, headers=UA, follow_redirects=True)
        if "news.google.com" not in str(r.url):
            return str(r.url)
    except Exception:
        pass
    return link

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
            arts.append(Article(title=title, link=_real_url(e.link), source=src).model_dump())
    logger.info(f"📰 Fetched {len(arts)} fresh articles (real publisher URLs)")
    return {"articles": arts}

# ------------------------------------------------------------------
# 2. LEARN
# ------------------------------------------------------------------
def learn(state):
    if not settings.zernio_api_key:
        logger.info("📊 Zernio not connected — skipping learn loop")
        return {}
    try:
        r = httpx.get(f"{ZERNIO}/posts", params={"limit": 12},
                      headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        rows = r.get("posts", r.get("data", []))
        json.dump(rows, open(ANA, "w", encoding="utf-8"), indent=1, default=str)
        logger.info(f"📊 Insights saved: {len(rows)} recent reels")
    except Exception as e:
        logger.warning(f"insights skipped: {e}")
    return {}

# ------------------------------------------------------------------
# 3. SELECT STORY
# ------------------------------------------------------------------
def select_story(state):
    hist = _load(HIST).get("recent", [])
    ana = _load(ANA)
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
# TRUTH TOOLS (M003/M004/M007/M008 guards)
# ------------------------------------------------------------------
KNOWN_LOC = ["delhi","mumbai","bihar","noida","gurugram","jaipur","kanpur","patna","kolkata",
             "chennai","bengaluru","hyderabad","ahmedabad","pune","lucknow","india","nepal",
             "china","usa","us","america","russia","uk","pakistan","bangladesh","sri lanka",
             "jammu","kashmir","manipur","assam","uttar pradesh","madhya pradesh","maharashtra",
             "gujarat","rajasthan","punjab","tamil nadu","kerala","west bengal","odisha","munger"]

def _cut(s, n):
    """Word-safe truncation — never 'DELH' / 'STOL' / 'RESIDENC'."""
    s = s or ""
    if len(s) <= n: return s
    cut = s[:n]
    return (cut[:cut.rfind(" ")] or cut).strip()

# ------------------------------------------------------------------
# 4. EXTRACT SCHEMA
# ------------------------------------------------------------------
def extract_schema(state):
    from . import scraper
    a = state["articles"][state["selected"]["article_index"]]
    others = "\n".join(f"- {t['title']}" for t in state["articles"][:6] if t is not a)
    scraped = scraper.deep_scrape(a["link"])
    real_quotes = "\n".join(f'- "{q}"' for q in scraped.get("quotes", [])) or "No direct quotes found."
    real_date = scraped.get("date", "today")
    lang_hint = ("narration lines MUST be in simple spoken Hindi, Devanagari script. "
                 if settings.narration_lang == "hi"
                 else "narration lines MUST be in crisp English. ")
    prompt = f"""You are the editor of @indiainlast24hr-style reel.
STORY: {a['title']} ({a['source']}) - Published: {real_date}
{lang_hint}All ON-SCREEN text stays ENGLISH CAPS.
TOTAL narration across ALL scenes must stay under 80 seconds.

CRITICAL TRUTH RULES (DO NOT INVENT):
1. quote_text MUST be copied EXACTLY verbatim from this list of real quotes:
{real_quotes}
2. stat_text MUST be exact numbers found in the article body (e.g. "3000+ DEAD").
3. breaking_headline MUST be a verbatim substring of the RSS title. DO NOT MISSPELL WORDS.
4. map "pin" MUST be a city/place name from the story (e.g. "Delhi", "Munger"), NEVER a person or random word.

Build 6-9 scenes:
1) map scene (country, pin location, overlay_text hook, narration = hook line)
2-5) mix of clip, article (masthead+headline), quote (quote_text+person)
6+) 1-2 breaking scenes from OTHER headlines.
Other headlines:\n{others}
Caption + 8 hashtags."""
    resp = llm_create(prompt, StorySchema)
    schema = resp.model_dump()

    if len(schema.get("scenes", [])) < 3:
        logger.warning("⚠️ Fallback schema built")
        t = a["title"]
        schema["scenes"] = [
            Scene(type="map", country="India", pin=_cut(t, 20), overlay_text=_cut(t, 44).upper(), narration=t).model_dump(),
            Scene(type="article", masthead=a["source"], headline=t, narration=t).model_dump(),
            Scene(type="breaking", breaking_headline=_cut(t, 60).upper(), breaking_sub=a["source"],
                  breaking_image_query="news", narration=t).model_dump(),
        ]
        schema.setdefault("caption", t)
        schema.setdefault("hashtags", ["india", "news"])
    return {"schema": schema, "article": a, "_scraped": scraped}

def _enforce_truth(scenes, state):
    """Truth Layer that ALWAYS runs, regardless of graph wiring."""
    a = state.get("article") or {}
    rss = a.get("title", "")
    src = (a.get("source") or "").upper()
    quotes = (state.get("_scraped") or {}).get("quotes", [])
    low = rss.lower()

    for sc in scenes:
        if sc.type == "map":
            pin = (sc.pin or "").lower()
            if not any(k in pin for k in KNOWN_LOC):
                fix = next((k for k in KNOWN_LOC if k in low), None)
                sc.pin = fix.title() if fix else (sc.country or "India")
            sc.overlay_text = (_cut(rss, 44).upper() or sc.overlay_text)
        if sc.type == "breaking" and src and (sc.breaking_sub or "").upper().startswith(src):
            sc.breaking_headline = _cut(rss, 60).upper()
        if sc.type == "quote" and quotes and sc.quote_text not in quotes:
            sc.quote_text = quotes[0]

    if not any(sc.type == "clip" for sc in scenes):
        kw = " ".join(w for w in rss.split() if len(w) > 4)[:40] or "news"
        scenes.insert(1, Scene(type="clip", clip_query=kw.lower(), narration=rss))
    return scenes

def proofread_schema(state):
    schema = state["schema"]
    a = state["article"]
    rss_title = a["title"]
    real_quotes = (state.get("_scraped") or {}).get("quotes", [])
    head_low = rss_title.lower()
    for scene in schema.get("scenes", []):
        if scene.get("type") == "breaking" and scene.get("breaking_sub", "").upper().startswith(a["source"].upper()):
            scene["breaking_headline"] = _cut(rss_title, 60).upper()
        if scene.get("type") == "quote" and real_quotes:
            scene["quote_text"] = real_quotes[0]
        if scene.get("type") == "map":
            pin = (scene.get("pin") or "").lower()
            if not any(k in pin for k in KNOWN_LOC):
                fix = next((k for k in KNOWN_LOC if k in head_low), None)
                scene["pin"] = fix.title() if fix else (scene.get("country") or "India")
    if not any(s.get("type") == "clip" for s in schema["scenes"]):
        kw = " ".join([w for w in rss_title.split() if len(w) > 4][:3]) or "news"
        schema["scenes"].insert(1, Scene(type="clip", clip_query=kw.lower(), narration=rss_title).model_dump())
    return {"schema": schema}

# ------------------------------------------------------------------
# 5. RENDER SCENES
# ------------------------------------------------------------------
def render_scenes(state):
    from . import editor, fx, media, tts
    scenes = [Scene(**s) for s in state["schema"]["scenes"]]
    scenes = _enforce_truth(scenes, state)

    for sc in scenes:
        if sc.type in ("article", "breaking") and not sc.image_url:
            target = (sc.headline or sc.breaking_headline or "").lower()
            hit = next((a for a in state["articles"]
                        if sum(w in a["title"].lower() for w in target.split()[:5]) >= 2), None)
            if hit:
                sc.image_url = media.og_image(hit["link"])
                sc.article_link = hit["link"]

    main_link = state.get("article", {}).get("link")
    for sc in scenes:
        if sc.type in ("clip", "article", "quote") and not sc.article_link:
            sc.article_link = main_link

    take = tts.speak_full([sc.narration for sc in scenes], "full")
    segs = editor.render_all(scenes, take)
    segs.append(fx.outro_video())
    return {"segments": segs}

# ------------------------------------------------------------------
# 6. ASSEMBLE / 7. PUBLISH
# ------------------------------------------------------------------
def assemble(state):
    from . import editor
    final = os.path.join(settings.output_dir, "reel_final.mp4")
    editor.assemble(state["segments"], final)
    return {"final": final}

def publish(state):
    from . import publisher
    publisher.publish(state["final"],
                      state["schema"].get("caption", ""),
                      state["schema"].get("hashtags", []))
    return {}

# ------------------------------------------------------------------
# legacy TTS (reference only)
# ------------------------------------------------------------------
async def _tts(text: str, mp3: str):
    timings = []
    comm = edge_tts.Communicate(text, settings.tts_voice, rate="+8%")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio": f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                timings.append((chunk["text"], chunk["offset"] / 1e7,
                                (chunk["offset"] + chunk["duration"]) / 1e7))
    return timings

def synthesize_voice(state):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, "voice.mp3")
    timings = asyncio.run(_tts(state["schema"]["narration"], mp3))
    return {"voice": {"mp3": mp3, "words": timings}}

# ------------------------------------------------------------------
# 8. SELECT FORMAT
# ------------------------------------------------------------------
def select_format(state):
    ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    hour = ist_now.hour
    fmt = "roundup" if 18 <= hour < 21 else "deep_dive"
    logger.info(f"⏰ Time is {hour}:00 IST → Format chosen: {fmt.upper()}")
    return {"reel_format": fmt}

# ------------------------------------------------------------------
# 9. EXTRACT ROUNDUP
# ------------------------------------------------------------------
def extract_roundup(state):
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in enumerate(state["articles"][:15]))
    lang_hint = "simple spoken Hindi" if settings.narration_lang == "hi" else "crisp English"
    prompt = f"""You are the editor of @indiainlast24hr. Create a fast-paced "Top 8 Headlines" reel.
Intro: A catchy hook in {lang_hint}.
Scenes: Pick the 8 most important/viral DISTINCT stories from the feed below.
Each scene needs a short ENGLISH CAPS headline, a 1-sentence {lang_hint} narration, and an image query.
Feed:\n{listing}
Also write caption + 8 hashtags.

CRITICAL VISUAL RULES:
- image_query must be GENERIC searchable footage keywords (e.g. "stock market crash", "cricket stadium crowd"), NEVER proper nouns.
- Never use graphic, gory, or disturbing imagery descriptions."""
    resp = llm_create(prompt, RoundupSchema)
    items = resp.scenes or [
        RoundupScene(headline=_cut(x["title"], 60).upper(), narration=x["title"],
                     image_query="news") for x in state["articles"][:8]
    ]
    scenes = [Scene(type="breaking", breaking_headline="INDIA IN LAST 24 HOURS",
                    breaking_sub="TOP 8 HEADLINES", breaking_image_query="india news studio",
                    narration=resp.intro_narration or "आइए जानते हैं आज की बड़ी खबरें").model_dump()]
    for i, item in enumerate(items):
        scenes.append(Scene(type="breaking", breaking_headline=item.headline,
                            breaking_sub=f"#{i+1}", breaking_image_query=item.image_query,
                            narration=item.narration).model_dump())
    return {"schema": {"scenes": scenes, "caption": resp.caption, "hashtags": resp.hashtags},
            "article": state["articles"][0]}

# ------------------------------------------------------------------
# 10. AUTO REPLY TO COMMENTS
# ------------------------------------------------------------------
def reply_comments(state):
    if not settings.zernio_api_key: return {}
    try:
        posts = httpx.get(f"{ZERNIO}/posts", params={"limit": 3},
                          headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        post_ids = [p.get("id") or p.get("_id") for p in posts.get("posts", []) if p.get("platform") == "instagram"]
        if not post_ids: return {}
        comments_res = httpx.get(f"{ZERNIO}/comments", params={"postId": post_ids[0], "limit": 5},
                                 headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        comments = comments_res.get("comments", comments_res.get("data", []))
        replied = 0
        for c in comments:
            c_id = c.get("id") or c.get("_id")
            c_text = c.get("text", c.get("message", ""))
            c_user = c.get("user", {}).get("name", "User")
            if c.get("isRead") or c.get("isOwner") or replied >= 2: continue
            reply_resp = llm_create(
                f"Write a 1-sentence friendly reply to this Instagram comment from {c_user}: '{c_text}'. Ask a question back. Reply ONLY with the text.",
                CommentReply)
            reply_text = reply_resp.text if hasattr(reply_resp, 'text') else str(reply_resp)
            httpx.post(f"{ZERNIO}/comments/{c_id}/reply",
                       headers={"Authorization": f"Bearer {settings.zernio_api_key}"},
                       json={"text": reply_text}, timeout=30)
            replied += 1
            logger.info(f"💬 Replied to {c_user}")
    except Exception as e:
        logger.warning(f"comment reply loop skipped: {e}")
    return {}