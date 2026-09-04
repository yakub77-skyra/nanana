import datetime, asyncio, os, json, re, time
import feedparser, instructor, edge_tts, httpx
from openai import OpenAI
from loguru import logger
try: import googlenewsdecoder
except Exception: googlenewsdecoder = None

from .config import settings
from .schemas import (Article, SelectedStory, StorySchema, Scene,
                      RoundupSchema, RoundupScene, CommentReply)

llm = instructor.from_openai(OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
FEEDS = {
    "top": "https://news.google.com/rss/headlines/section/topic/Top_stories?hl=en-IN&gl=IN&ceid=IN:en",
    "india": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
}
ZERNIO = "https://zernio.com/api/v1"
HIST, ANA = "history.json", "analytics.json"
LIVE_CACHE = os.path.join(settings.output_dir, "live_models_cache.json")
GENERIC = {"", "NEWS", "INDIA NEWS", "BREAKING", "BREAKING NEWS", "HEADLINE", "NEWS SOURCE"}

def _fetch_live_free_models():
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20).json()
        return [m["id"] for m in r.get("data", []) if m.get("pricing", {}).get("prompt") == "0" and m.get("pricing", {}).get("completion") == "0"]
    except Exception: return []

def _live_free_models_cached():
    if os.path.exists(LIVE_CACHE):
        try:
            data = json.load(open(LIVE_CACHE))
            if time.time() - data.get("ts", 0) < 6 * 3600 and data.get("models"): return data["models"]
        except Exception: pass
    models = _fetch_live_free_models()
    try: json.dump({"ts": time.time(), "models": models}, open(LIVE_CACHE, "w"))
    except Exception: pass
    return models

def _model_chain():
    pref = [m.strip() for m in settings.llm_fallbacks.split(",") if m.strip()]
    if settings.llm_model: pref = [settings.llm_model] + pref
    live = _live_free_models_cached()
    chain = [m for m in pref if m in live]
    chain += [m for m in live if m not in chain][:3]
    return chain or pref

def llm_create(prompt, response_model=None):
    last = RuntimeError("No free models available")
    tried_compact = False
    for model in _model_chain():
        try:
            if response_model:
                resp = llm.chat.completions.create(model=model, response_model=response_model, max_retries=2, messages=[{"role": "user", "content": prompt}])
                if resp is None: raise ValueError("None")
                return resp
            r = llm.chat.completions.create(model=model, max_retries=2, messages=[{"role": "user", "content": prompt}])
            if not r or not r.choices: raise ValueError("empty")
            return r.choices[0].message.content
        except Exception as e:
            err_str = str(e); last = e
            if "400" in err_str and not tried_compact and response_model:
                tried_compact = True
                try: return llm.chat.completions.create(model=model, response_model=response_model, max_retries=1, messages=[{"role": "user", "content": prompt[:1200] + "\n..."}])
                except Exception: pass
            logger.warning(f"{model} failed → next")
    raise last

def _load(p): return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}

def _real_url(link):
    if "news.google.com" not in link: return link
    if googlenewsdecoder:
        try:
            res = googlenewsdecoder.gnewsdecoder(link)
            if isinstance(res, dict) and res.get("decoded_url"): return res["decoded_url"]
        except Exception: pass
    try:
        r = httpx.get(link, timeout=10, headers=UA, follow_redirects=True)
        if "news.google.com" not in str(r.url): return str(r.url)
    except Exception: pass
    return link

KNOWN_LOC = ["delhi", "mumbai", "bihar", "noida", "gurugram", "jaipur", "kanpur", "patna", "kolkata", "chennai",
    "bengaluru", "hyderabad", "ahmedabad", "pune", "lucknow", "india", "nepal", "china", "usa", "russia", "uk",
    "pakistan", "bangladesh", "sri lanka", "jammu", "kashmir", "manipur", "assam", "uttar pradesh",
    "madhya pradesh", "maharashtra", "gujarat", "rajasthan", "punjab", "tamil nadu", "kerala", "west bengal",
    "odisha", "nagpur", "goa", "haryana", "jharkhand", "chhattisgarh", "telangana", "andhra pradesh"]

def _cut(s, n):
    s = s or ""
    if len(s) <= n: return s
    cut = s[:n]; cut = cut[:cut.rfind(" ")] or cut
    words = cut.split()
    bad = {"A", "AN", "THE", "OF", "TO", "IN", "FOR", "WITH", "ON", "AT", "S", "AND", "OR", "AS", "BY", "FROM"}
    while words and (words[-1].upper().strip(".") in bad or words[-1].upper().endswith("'S") or words[-1].endswith(",")):
        words.pop()
    return " ".join(words).strip()

def _smart_headline(t, max_chars=40):
    """Strip source suffix + generic prefix, keep the REAL story text."""
    t = (t or "NEWS").strip()
    for sep in (" - ", " | ", " – "):
        if sep in t: t = t.split(sep)[0]
    low = t.lower()
    for pre in ("india news:", "breaking:", "breaking news:", "watch:", "latest:", "news:"):
        if low.startswith(pre):
            t = t[len(pre):].strip(); break
    if len(t) < 6: t = "NEWS"
    return _cut(t, max_chars).upper()

def _guard_text(s, max_chars=32):
    return _smart_headline(s, max_chars)

def _doctor(state):
    logger.info("🩺 Running startup diagnostics...")
    live = _live_free_models_cached()
    if live: logger.info(f"✅ {len(live)} free models live")
    else: logger.warning("⚠️ No free models detected")
    return {}

def fetch_news(state):
    arts, seen = [], set()
    for url in FEEDS.values():
        for e in feedparser.parse(url).entries[:15]:
            title = e.get("title", "")
            if not title or title in seen: continue
            seen.add(title)
            src = (e.get("source", {}).get("title", "") if isinstance(e.get("source"), dict) else "")
            arts.append(Article(title=title, link=_real_url(e.link), source=src).model_dump())
    logger.info(f"Fetched {len(arts)} fresh articles")
    return {"articles": arts}

def learn(state):
    if not settings.zernio_api_key: return {}
    try:
        r = httpx.get(f"{ZERNIO}/posts", params={"limit": 12}, headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        rows = r.get("posts", r.get("data", []))
        json.dump(rows, open(ANA, "w", encoding="utf-8"), indent=1, default=str)
    except Exception: pass
    return {}

def select_story(state):
    hist = _load(HIST).get("recent", [])
    candidates = [(i, a) for i, a in enumerate(state["articles"]) if a["title"] not in hist]
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in (candidates or list(enumerate(state["articles"]))))
    prompt = f"Pick ONE story index (0-{len(state['articles'])-1}) with highest viral potential. Feed:\n{listing}"
    try:
        resp = llm_create(prompt, SelectedStory)
        idx = int(resp.article_index) if resp and hasattr(resp, "article_index") else 0
    except Exception: idx = 0
    idx = max(0, min(idx, len(state["articles"]) - 1))
    h = _load(HIST)
    h["recent"] = (h.get("recent", []) + [state["articles"][idx]["title"]])[-10:]
    json.dump(h, open(HIST, "w", encoding="utf-8"), ensure_ascii=False)
    logger.success(f"Selected: {state['articles'][idx]['title']}")
    return {"selected": {"article_index": idx}}

def extract_schema(state):
    from . import scraper
    idx = (state.get("selected") or {}).get("article_index", 0)
    articles = state.get("articles") or []
    if not articles or idx < 0 or idx >= len(articles): idx = 0
    a = articles[idx]
    others_titles = [t["title"] for t in articles[:6] if t is not a]
    scraped = scraper.deep_scrape(a["link"])
    prompt = f"""Editor of @indiainlast24hr. STORY: {a['title']} ({a['source']}).
Build 8-10 scenes in order: title_card, map_intro, news_frame, article_card, keyword_text, stat_callout, quote_card, breaking_card.
FILL EVERY FIELD PER TYPE (no empty values allowed):
- title_card: overlay_text (punchy 4-8 word CAPS), narration (Hinglish hook)
- map_intro: overlay_text, pin, narration
- news_frame: headline (full CAPS headline), location, state, narration, clip_query
- article_card: masthead (real source name), headline, narration, clip_query
- keyword_text: keyword (ONE powerful word e.g. SATELLITE), narration, clip_query
- stat_callout: stat_text (EXACT number from article e.g. "31.1 MILLION"), stat_label, narration
- quote_card: quote_text (verbatim from article), person, narration
- breaking_card: breaking_headline (OTHER story CAPS: {others_titles[0] if others_titles else 'INDIA NEWS UPDATE'}), breaking_sub (its source), narration
On-screen text ENGLISH CAPS. Narration casual Hinglish. Return caption + 5 hashtags."""
    try:
        resp = llm_create(prompt, StorySchema)
        schema = resp.model_dump() if resp else None
    except Exception: schema = None
    if not schema or len(schema.get("scenes", [])) < 3:
        t = a["title"]
        schema = {"scenes": [
            Scene(type="title_card", overlay_text=_smart_headline(t, 32), narration=t, theme="purple").model_dump(),
            Scene(type="map_intro", country="India", pin="India", overlay_text=_smart_headline(t, 32), narration=t, theme="purple").model_dump(),
            Scene(type="news_frame", frame_number=1, headline=_smart_headline(t, 60), location="INDIA", style="deep", narration=t, theme="purple").model_dump(),
            Scene(type="breaking_card", breaking_headline=_smart_headline(others_titles[0] if others_titles else t, 60), breaking_sub=a["source"], narration=others_titles[0] if others_titles else t, theme="purple").model_dump()
        ], "caption": t, "hashtags": ["india", "news"]}
    return {"schema": schema, "article": a, "_scraped": scraped}

def _backfill_narration(scenes, article_title):
    for sc in scenes:
        if not sc.narration:
            if sc.type == "title_card": sc.narration = article_title
            elif sc.type == "map_intro": sc.narration = sc.overlay_text or article_title
            elif sc.type in ("news_frame", "breaking_card", "article_card"): sc.narration = sc.headline or sc.breaking_headline or article_title
            elif sc.type == "quote_card": sc.narration = sc.quote_text or article_title
            elif sc.type in ("stat_overlay", "stat_callout"): sc.narration = f"The number is {sc.stat_text}" if sc.stat_text else article_title
            elif sc.type == "keyword_text": sc.narration = sc.keyword or article_title
            else: sc.narration = article_title

def _enforce_truth(scenes, state):
    a = state.get("article") or {}
    rss = a.get("title", "")
    quotes = (state.get("_scraped") or {}).get("quotes", [])
    smart = _smart_headline(rss)
    nums = re.findall(r"\d+(?:[.,]\d+)?(?:\s?(?:%|crore|lakh|million|billion|tonnes|km|kg|days))?", rss, re.I)

    out = []
    for sc in scenes:
        if not sc.headline: sc.headline = smart
        if not sc.breaking_headline: sc.breaking_headline = _smart_headline(rss, 60)
        if sc.type == "title_card" and (not sc.overlay_text or sc.overlay_text.upper() in GENERIC):
            sc.overlay_text = smart[:32]
        if sc.type in ("map_intro", "location_highlight"):
            if not sc.overlay_text or sc.overlay_text.upper() in GENERIC: sc.overlay_text = smart[:32]
            pin = (sc.pin or "").lower()
            if not any(k in pin for k in KNOWN_LOC):
                fix = next((k for k in KNOWN_LOC if k in rss.lower()), None)
                sc.pin = fix.title() if fix else "India"
        if sc.type == "article_card" and (not sc.masthead or sc.masthead.upper() in GENERIC):
            sc.masthead = (a.get("source") or "THE TIMES OF INDIA").title()
        if sc.type == "keyword_text" and (not sc.keyword or sc.keyword.upper() in GENERIC):
            sc.keyword = max([w for w in rss.split() if len(w) > 4], key=len, default="NEWS").upper()
        if sc.type in ("stat_overlay", "stat_callout"):
            if not sc.stat_text or sc.stat_text == "0":
                sc.stat_text = nums[0].strip() if nums else None
            if not sc.stat_text:
                sc.type = "news_frame"
        if sc.type == "breaking_card" and (not sc.breaking_sub or sc.breaking_sub.upper() in GENERIC):
            sc.breaking_sub = a.get("source") or ""
        if sc.type == "quote_card" and quotes and sc.quote_text not in quotes:
            sc.quote_text = quotes[0]
        if sc.type in ("quote_card", "stat_callout") and not sc.person:
            sc.person = (a.get("source") or "Official").title()
        out.append(sc)

    seen_q = set(); final = []
    n = 0
    for sc in out:
        if sc.type in ("quote_card", "quote"):
            key = (sc.quote_text or "").strip()[:100]
            if not key or key in seen_q: continue
            seen_q.add(key)
        if sc.type == "news_frame":
            n += 1; sc.frame_number = n
        final.append(sc)
    if not any(sc.type in ("clip", "news_frame", "footage_highlight") for sc in final):
        final.insert(1, Scene(type="news_frame", frame_number=1, headline=smart, location="INDIA",
                              style="deep", narration=rss, theme="purple").model_dump())
    return final

def proofread_schema(state):
    schema = state.get("schema") or {"scenes": [], "caption": "", "hashtags": []}
    a = state.get("article") or {}
    rss_title = a.get("title", "NEWS")
    for scene in schema.get("scenes", []):
        if scene.get("type") == "title_card" and (not scene.get("overlay_text") or scene["overlay_text"].upper() in GENERIC):
            scene["overlay_text"] = _smart_headline(rss_title, 32)
        if scene.get("type") == "breaking_card" and (scene.get("breaking_sub") or "").upper().startswith((a.get("source") or "").upper()):
            scene["breaking_headline"] = _cut(rss_title, 60).upper()
    if schema["scenes"] and schema["scenes"][0].get("type") != "title_card" and state.get("reel_format") != "roundup":
        schema["scenes"].insert(0, Scene(type="title_card", overlay_text=_smart_headline(rss_title, 32), narration=rss_title, theme="purple").model_dump())
    return {"schema": schema}

def render_scenes(state):
    from . import editor, fx, media
    scenes = [Scene(**s) for s in state["schema"]["scenes"]]
    scenes = _enforce_truth(scenes, state)
    _backfill_narration(scenes, state.get("article", {}).get("title", "News update"))
    main_link = state.get("article", {}).get("link")
    for sc in scenes:
        if not sc.article_link: sc.article_link = main_link
    pool = []
    for a in state["articles"][:8]:
        try: pool.append((a["title"], media.og_image(a["link"])))
        except Exception: pool.append((a["title"], None))
    editor.FEED_IMAGES = pool
    segs = editor.render_all(scenes, None, fmt=state.get("reel_format", "deep_dive"))
    segs.append(fx.outro_video())
    return {"segments": segs}

def assemble(state):
    from . import editor
    final = os.path.join(settings.output_dir, "reel_final.mp4")
    editor.assemble(state["segments"], final)
    logger.info("=" * 40)
    logger.info("🎬 REEL SUMMARY")
    logger.info(f"✅ Total Scenes Rendered: {len(state['segments']) - 1}")
    logger.info(f"✅ Final Video: {final}")
    logger.info("=" * 40)
    return {"final": final}

def publish(state):
    from . import publisher
    try: return {"publish_result": publisher.publish(state["final"], state["schema"].get("caption", ""), state["schema"].get("hashtags", []))}
    except Exception as e: logger.error(f"Publish failed: {e}"); return {}

def select_format(state):
    hour = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).hour
    fmt = "roundup" if 18 <= hour < 21 else "deep_dive"
    logger.info(f"Time {hour}:00 IST → Format: {fmt.upper()}")
    return {"reel_format": fmt}

def extract_roundup(state):
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in enumerate(state["articles"][:15]))
    try: resp = llm_create(f"Top 8 headlines reel. Feed:\n{listing}", RoundupSchema)
    except Exception: resp = None
    items = (resp.scenes if resp and hasattr(resp, "scenes") else []) or \
            [RoundupScene(headline=_cut(x["title"], 60).upper(), narration=x["title"], image_query="news") for x in state["articles"][:8]]
    intro = (resp.intro_narration if resp and hasattr(resp, "intro_narration") else "") or "आइए जानते हैं आज की बड़ी खबरें"
    STATES = ["andhra pradesh", "assam", "bihar", "chhattisgarh", "delhi", "goa", "gujarat", "haryana",
              "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra",
              "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan", "sikkim",
              "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
              "jammu and kashmir", "ladakh"]
    ALIASES = {"jammu kashmir": "jammu and kashmir", "j&k": "jammu and kashmir", "orissa": "odisha",
               "uk": "uttarakhand", "up": "uttar pradesh"}
    built = []
    for i, item in enumerate(items[:8]):
        loc = (item.location or "").lower()
        head = (item.headline or "").lower()
        state_name = item.state or ""
        if not state_name:
            for s in STATES:
                if s in loc or s in head: state_name = s; break
        state_name = ALIASES.get(state_name.lower(), state_name).title() if state_name else ""
        disaster = any(w in head for w in ["death", "kill", "murder", "crash", "flood", "fire", "attack", "bomb", "terror", "rape", "violence", "disaster", "tragedy"])
        built.append(Scene(type="news_frame", frame_number=i + 1,
                           breaking_headline=_cut(item.headline, 60).upper(), headline=_cut(item.headline, 60).upper(),
                           location=item.location or "INDIA", state=state_name,
                           style="roundup", breaking_image_query=item.image_query,
                           narration=item.narration, theme="red" if disaster else "purple"))
    scenes = [Scene(type="map_intro", country="India", pin="India", overlay_text="INDIA IN LAST 24 HOURS", narration=intro, theme="purple").model_dump()]
    scenes += [sc.model_dump() for sc in built]
    return {"schema": {"scenes": scenes, "caption": (resp.caption if resp and hasattr(resp, "caption") else "") or state["articles"][0]["title"],
                       "hashtags": (resp.hashtags if resp and hasattr(resp, "hashtags") else []) or ["india", "news"]},
            "article": state["articles"][0]}

async def _tts(text: str, mp3: str):
    timings = []
    comm = edge_tts.Communicate(text, settings.tts_voice, rate="+8%")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio": f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                timings.append((chunk["text"], chunk["offset"] / 1e7, (chunk["offset"] + chunk["duration"]) / 1e7))
    return timings

def synthesize_voice(state):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, "voice.mp3")
    timings = asyncio.run(_tts(state["schema"]["narration"], mp3))
    return {"voice": {"mp3": mp3, "words": timings}}

def reply_comments(state): return {}