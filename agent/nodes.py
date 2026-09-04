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

# ============================================================
# LIVE MODEL CHAIN + SMART RETRY
# ============================================================
def _fetch_live_free_models():
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20).json()
        return [m["id"] for m in r.get("data", [])
                if m.get("pricing", {}).get("prompt") == "0"
                and m.get("pricing", {}).get("completion") == "0"]
    except Exception: return []

def _live_free_models_cached():
    if os.path.exists(LIVE_CACHE):
        try:
            data = json.load(open(LIVE_CACHE))
            if time.time() - data.get("ts", 0) < 6 * 3600 and data.get("models"):
                return data["models"]
        except Exception: pass
    models = _fetch_live_free_models()
    try:
        os.makedirs(os.path.dirname(LIVE_CACHE) or ".", exist_ok=True)
        json.dump({"ts": time.time(), "models": models}, open(LIVE_CACHE, "w"))
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
                resp = llm.chat.completions.create(
                    model=model, response_model=response_model, max_retries=2,
                    messages=[{"role": "user", "content": prompt}])
                if resp is None: raise ValueError("LLM returned None")
                return resp
            r = llm.chat.completions.create(
                model=model, max_retries=2,
                messages=[{"role": "user", "content": prompt}])
            if not r or not r.choices: raise ValueError("empty choices")
            return r.choices[0].message.content
        except Exception as e:
            err_str = str(e); last = e
            if "400" in err_str and not tried_compact and response_model:
                tried_compact = True
                logger.warning(f"{model} → 400, retrying with compact prompt")
                try:
                    return llm.chat.completions.create(
                        model=model, response_model=response_model, max_retries=1,
                        messages=[{"role": "user", "content": prompt[:1200] + "\n..."}])
                except Exception as e2: logger.warning(f"compact retry failed: {e2}")
            logger.warning(f"{model} failed → next")
    raise last

# ============================================================
# HELPERS
# ============================================================
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

KNOWN_LOC = ["delhi","mumbai","bihar","noida","gurugram","jaipur","kanpur","patna","kolkata","chennai",
    "bengaluru","hyderabad","ahmedabad","pune","lucknow","india","nepal","china","usa","russia","uk",
    "pakistan","bangladesh","sri lanka","jammu","kashmir","manipur","assam","uttar pradesh",
    "madhya pradesh","maharashtra","gujarat","rajasthan","punjab","tamil nadu","kerala","west bengal",
    "odisha","nagpur","goa","haryana","jharkhand","chhattisgarh","telangana","andhra pradesh"]

def _cut(s, n):
    s = s or ""
    if len(s) <= n: return s
    cut = s[:n]; cut = cut[:cut.rfind(" ")] or cut
    words = cut.split()
    bad = {"A","AN","THE","OF","TO","IN","FOR","WITH","ON","AT","S","AND","OR","AS","BY","FROM"}
    while words and (words[-1].upper().strip(".") in bad or words[-1].upper().endswith("'S") or words[-1].endswith(",")):
        words.pop()
    return " ".join(words).strip()

def _guard_text(s, max_chars=28): return _cut(s, max_chars).upper() if s else "NEWS"

# ============================================================
# STARTUP DOCTOR
# ============================================================
def _doctor(state):
    logger.info("🩺 Running startup diagnostics...")
    live = _live_free_models_cached()
    if live: logger.info(f"✅ {len(live)} free models live on OpenRouter")
    else: logger.warning("⚠️ No free models detected — will use fallback chain")
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=10,
                      params={"action": "query", "meta": "siteinfo", "format": "json"})
        logger.info(f"{'✅' if r.status_code==200 else '⚠️'} Wikimedia HTTP {r.status_code}")
    except Exception as e: logger.warning(f"⚠️ Wikimedia unreachable: {e}")
    if settings.zernio_api_key:
        try:
            r = httpx.get(f"{ZERNIO}/posts", params={"limit": 1},
                          headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=10)
            logger.info(f"{'✅' if r.status_code==200 else '⚠️'} Zernio HTTP {r.status_code}")
        except Exception as e: logger.warning(f"⚠️ Zernio unreachable: {e}")
    return {}

# ============================================================
# 1. FETCH
# ============================================================
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

# 2. LEARN
def learn(state):
    if not settings.zernio_api_key: return {}
    try:
        r = httpx.get(f"{ZERNIO}/posts", params={"limit": 12},
                      headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        rows = r.get("posts", r.get("data", []))
        json.dump(rows, open(ANA, "w", encoding="utf-8"), indent=1, default=str)
        logger.info(f"Insights saved: {len(rows)}")
    except Exception as e: logger.warning(f"insights skipped: {e}")
    return {}

# 3. SELECT STORY
def select_story(state):
    hist = _load(HIST).get("recent", [])
    ana = _load(ANA)
    if not isinstance(ana, list): ana = []
    winners = "\n".join(f"- {m.get('content','')[:80]} -> {m.get('likeCount',0)} plays" for m in ana[:3]) or "none"
    candidates = [(i, a) for i, a in enumerate(state["articles"]) if a["title"] not in hist]
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in candidates)
    if not listing:
        listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in enumerate(state["articles"]))
    prompt = f"""Pick ONE story with highest viral potential for @indiainlast24hr.
Prioritize: disaster, politics, crime, money, public emotion, national impact.
Do NOT repeat: {', '.join(hist[-5:])}
Feed:
{listing}
Return article_index as int."""
    try:
        resp = llm_create(prompt, SelectedStory)
        idx = int(resp.article_index) if resp and hasattr(resp, "article_index") else 0
    except Exception as e:
        logger.warning(f"LLM selection failed ({e}), using 0"); idx = 0
    idx = max(0, min(idx, len(state["articles"]) - 1))
    h = _load(HIST)
    h["recent"] = (h.get("recent", []) + [state["articles"][idx]["title"]])[-10:]
    json.dump(h, open(HIST, "w", encoding="utf-8"), ensure_ascii=False)
    logger.success(f"Selected: {state['articles'][idx]['title']}")
    return {"selected": {"article_index": idx}}

# ============================================================
# 4. EXTRACT SCHEMA + RICH FALLBACK
# ============================================================
def _build_rich_schema_from_scrape(a, scraped, others_titles):
    scenes = []
    t = a["title"]
    pin = next((k for k in KNOWN_LOC if k in t.lower()), "India").title()
    scenes.append(Scene(type="title_card", overlay_text=_guard_text(t), narration=t, theme="purple").model_dump())
    scenes.append(Scene(type="map_intro", country="India", pin=pin, overlay_text=_guard_text(t), narration=t, theme="purple").model_dump())
    scenes.append(Scene(type="news_frame", frame_number=1, headline=t.upper()[:60], location="INDIA", style="deep", narration=t, theme="purple").model_dump())
    quotes = scraped.get("quotes", [])
    if quotes:
        scenes.append(Scene(type="quote_card", quote_text=quotes[0], person=a.get("source",""), narration=quotes[0], theme="purple").model_dump())
    else:
        nums = re.findall(r'\d+(?:,\d{3})*(?:\.\d+)?(?:%| lakh| crore)?', a["title"])
        if nums:
            scenes.append(Scene(type="stat_callout", stat_text=nums[0], stat_label="reported", narration=f"The number reported is {nums[0]}", theme="purple").model_dump())
        else:
            scenes.append(Scene(type="location_highlight", country="India", pin=pin, overlay_text=_guard_text(t), narration=t, theme="red").model_dump())
    if others_titles:
        scenes.append(Scene(type="breaking_card", breaking_headline=others_titles[0][:60].upper(), breaking_sub=a["source"], narration=others_titles[0], theme="purple").model_dump())
    return {"scenes": scenes, "caption": t, "hashtags": ["india", "news", "breaking", pin.lower().replace(" ", "")]}

def extract_schema(state):
    from . import scraper
    selected = state.get("selected") or {}
    idx = selected.get("article_index", 0)
    articles = state.get("articles") or []
    if not articles or idx < 0 or idx >= len(articles): idx = 0
    a = articles[idx]
    others_titles = [t["title"] for t in articles[:6] if t is not a]
    others = "\n".join(f"- {t}" for t in others_titles)
    scraped = scraper.deep_scrape(a["link"])
    real_quotes = scraped.get("quotes", [])
    real_date = scraped.get("date", "today")
    lang_hint = ("Hinglish casual tone (bail/arrest/flood in English, rest Hindi Devanagari). "
                 if settings.narration_lang == "hi" else "crisp casual English. ")
    prompt = f"""You edit viral news reels for @indiainlast24hr.
STORY: {a['title']} ({a['source']}) {real_date}
STYLE: {lang_hint} On-screen text: ENGLISH CAPS only. Under 80s total.
QUOTES (verbatim only): {', '.join(real_quotes[:3]) or 'none'}
SCENES (use exactly these types in order):
1. title_card: overlay_text (4-8 words), narration=hook
2. map_intro: country=India, pin=real city, overlay_text=short headline
3. news_frame: frame_number=1, headline, location, style="deep"
4. keyword_text OR article_card
5. stat_callout OR stat_overlay
6. quote_card OR table_card
7. breaking_card: breaking_headline from OTHER story: {others_titles[0] if others_titles else a['title'][:50]}
Each needs: type, narration, clip_query (generic words), image_url.
Also return caption + 5 hashtags."""
    try:
        resp = llm_create(prompt, StorySchema)
        schema = resp.model_dump() if resp else None
    except Exception as e:
        logger.warning(f"LLM schema failed ({type(e).__name__}), using rich fallback")
        schema = None
    if not schema or len(schema.get("scenes", [])) < 3:
        logger.warning("Using rich no-LLM fallback schema")
        schema = _build_rich_schema_from_scrape(a, scraped, others_titles)
    if schema["scenes"] and schema["scenes"][0].get("type") != "title_card":
        t = a["title"]
        schema["scenes"].insert(0, Scene(type="title_card", overlay_text=_guard_text(t), narration=t, theme="purple").model_dump())
    return {"schema": schema, "article": a, "_scraped": scraped}

def _enforce_truth(scenes, state):
    a = state.get("article") or {}
    rss = a.get("title", ""); src = (a.get("source") or "").upper()
    quotes = (state.get("_scraped") or {}).get("quotes", []); low = rss.lower()
    for sc in scenes:
        if sc.type == "title_card": sc.overlay_text = _guard_text(rss)
        if sc.type in ("map_intro", "location_highlight"):
            pin = (sc.pin or "").lower()
            if not any(k in pin for k in KNOWN_LOC):
                fix = next((k for k in KNOWN_LOC if k in low), None)
                sc.pin = fix.title() if fix else (sc.country or "India")
            sc.overlay_text = _guard_text(rss)
        if sc.type == "breaking_card" and src and (sc.breaking_sub or "").upper().startswith(src):
            sc.breaking_headline = _cut(rss, 60).upper()
        if sc.type == "quote_card" and quotes and sc.quote_text not in quotes:
            sc.quote_text = quotes[0]
        if sc.type in ("quote_card", "stat_callout") and not sc.person:
            sc.person = (a.get("source") or "Official Statement").title()
    seen_q = set()
    for sc in list(scenes):
        if sc.type in ("quote_card", "quote"):
            key = (sc.quote_text or "").strip()[:100]
            if not key or key in seen_q: scenes.remove(sc)
            else: seen_q.add(key)
    if not any(sc.type in ("clip", "news_frame", "footage_highlight", "keyword_text") for sc in scenes):
        scenes.insert(1, Scene(type="news_frame", frame_number=1, headline=rss, location="INDIA",
                               style="deep", narration=rss, theme="purple").model_dump())
    return scenes

def proofread_schema(state):
    schema = state.get("schema") or {"scenes": [], "caption": "", "hashtags": []}
    a = state.get("article") or {}
    rss_title = a.get("title", "NEWS")
    real_quotes = (state.get("_scraped") or {}).get("quotes", [])
    head_low = rss_title.lower()
    
    for scene in schema.get("scenes", []):
        if scene.get("type") == "title_card": 
            scene["overlay_text"] = _guard_text(rss_title)
            
        # FIXED: Use `or ""` to handle Pydantic None values safely
        if scene.get("type") in ("breaking_card", "breaking") and (scene.get("breaking_sub") or "").upper().startswith((a.get("source") or "").upper()):
            scene["breaking_headline"] = _cut(rss_title, 60).upper()
            
        if scene.get("type") in ("quote_card", "quote") and real_quotes: 
            scene["quote_text"] = real_quotes[0]
            
        if scene.get("type") in ("map_intro", "location_highlight", "map"):
            pin = (scene.get("pin") or "").lower()
            if not any(k in pin for k in KNOWN_LOC):
                fix = next((k for k in KNOWN_LOC if k in head_low), None)
                scene["pin"] = fix.title() if fix else (scene.get("country") or "India")
            scene["overlay_text"] = _guard_text(rss_title)
            
    seen_q = set()
    clean = []
    for scene in schema.get("scenes", []):
        if scene.get("type") in ("quote_card", "quote"):
            key = (scene.get("quote_text") or "").strip()[:100]
            if not key or key in seen_q: continue
            seen_q.add(key)
        clean.append(scene)
    schema["scenes"] = clean
    
    if schema["scenes"] and schema["scenes"][0].get("type") != "title_card" and state.get("reel_format") != "roundup":
        schema["scenes"].insert(0, Scene(type="title_card", overlay_text=_guard_text(rss_title),
                                         narration=rss_title, theme="purple").model_dump())
                                         
    if not any(s.get("type") in ("clip", "news_frame", "footage_highlight", "keyword_text") for s in schema["scenes"]):
        schema["scenes"].insert(1, Scene(type="news_frame", frame_number=1, headline=rss_title,
                                         location="INDIA", style="deep", narration=rss_title, theme="purple").model_dump())
                                         
    return {"schema": schema}

# ============================================================
# 5. RENDER SCENES (per-scene TTS + feed pool)
# ============================================================
def render_scenes(state):
    from . import editor, fx, media
    scenes = [Scene(**s) for s in state["schema"]["scenes"]]
    scenes = _enforce_truth(scenes, state)
    # Populate feed image pool for editor
    pool = []
    for a in state["articles"][:8]:
        try: pool.append((a["title"], media.og_image(a["link"])))
        except Exception: pool.append((a["title"], None))
    editor.FEED_IMAGES = pool
    for sc in scenes:
        if sc.type in ("article_card", "breaking_card", "news_frame") and not sc.image_url:
            target = (sc.headline or sc.breaking_headline or "").lower()
            hit = next((a for a in state["articles"] if sum(w in a["title"].lower() for w in target.split()[:5]) >= 2), None)
            if hit:
                sc.image_url = media.og_image(hit["link"])
                sc.article_link = hit["link"]
    main_link = state.get("article", {}).get("link")
    for sc in scenes:
        if sc.type in ("clip", "article", "quote", "news_frame", "footage_highlight") and not sc.article_link:
            sc.article_link = main_link
    segs = editor.render_all(scenes, None, fmt=state.get("reel_format", "deep_dive"))
    segs.append(fx.outro_video())
    return {"segments": segs}

def assemble(state):
    from . import editor
    final = os.path.join(settings.output_dir, "reel_final.mp4")
    editor.assemble(state["segments"], final)
    return {"final": final}

def publish(state):
    from . import publisher
    try:
        result = publisher.publish(state["final"], state["schema"].get("caption", ""), state["schema"].get("hashtags", []))
        if isinstance(result, dict) and result.get("error"):
            logger.error(f"⚠️ Publish error: {result['error']} — check Zernio account/key match")
        return {"publish_result": result}
    except Exception as e:
        logger.error(f"⚠️ Publish failed: {e}")
        return {"publish_result": {"error": str(e)}}

async def _tts(text, mp3):
    timings = []
    comm = edge_tts.Communicate(text, settings.tts_voice, rate="+8%")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio": f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                timings.append((chunk["text"], chunk["offset"]/1e7, (chunk["offset"]+chunk["duration"])/1e7))
    return timings

def synthesize_voice(state):
    os.makedirs(settings.output_dir, exist_ok=True)
    mp3 = os.path.join(settings.output_dir, "voice.mp3")
    timings = asyncio.run(_tts(state["schema"]["narration"], mp3))
    return {"voice": {"mp3": mp3, "words": timings}}

def select_format(state):
    ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
    hour = ist_now.hour
    fmt = "roundup" if 18 <= hour < 21 else "deep_dive"
    logger.info(f"Time {hour}:00 IST → Format: {fmt.upper()}")
    return {"reel_format": fmt}

def extract_roundup(state):
    listing = "\n".join(f"[{i}] {a['source']}: {a['title']}" for i, a in enumerate(state["articles"][:15]))
    lang_hint = "Hinglish casual" if settings.narration_lang == "hi" else "crisp English"
    prompt = f"""Editor of @indiainlast24hr — Top 8 Headlines reel.
VISUAL: map_intro opening, then 8 news_frame scenes with state highlighted.
Intro hook in {lang_hint}: 'आइए जानते हैं पछिल्ले 24 ghanto mein kya hua'.
Each of 8 scenes: frame_number, 5-6 word ENGLISH CAPS headline, {lang_hint} narration, location, state (Indian state name), image_query (generic), theme (red for disaster).
Feed: {listing}
Return caption + 5 hashtags."""
    try: resp = llm_create(prompt, RoundupSchema)
    except Exception as e: logger.warning(f"Roundup LLM failed ({e}), using fallback"); resp = None
    items = (resp.scenes if resp and hasattr(resp, "scenes") else []) or \
            [RoundupScene(headline=_cut(x["title"], 60).upper(), narration=x["title"], image_query="news", location="INDIA") for x in state["articles"][:8]]
    intro = (resp.intro_narration if resp and hasattr(resp, "intro_narration") else "") or "आइए जानते हैं आज की बड़ी खबरें"
    caption = (resp.caption if resp and hasattr(resp, "caption") else "") or state["articles"][0]["title"]
    hashtags = (resp.hashtags if resp and hasattr(resp, "hashtags") else []) or ["india", "news"]
    STATES = ["telangana","andhra pradesh","maharashtra","gujarat","rajasthan","punjab","haryana",
              "delhi","west bengal","bihar","uttar pradesh","madhya pradesh","karnataka","tamil nadu",
              "kerala","odisha","assam","jharkhand","chhattisgarh","goa","nepal"]
    palette = ["purple","orange","green","olive","blue","purple","orange","green"]
    built = []
    for i, item in enumerate(items[:8]):
        disaster = any(w in item.headline.lower() for w in ["death","kill","murder","crash","flood","fire",
                                                             "attack","bomb","terror","rape","violence","disaster","tragedy"])
        theme = "red" if disaster else palette[i % len(palette)]
        loc = (item.location or "").lower(); head = (item.headline or "").lower()
        state_name = item.state or next((s for s in STATES if s in loc or s in head), "")
        built.append(Scene(type="news_frame", frame_number=i+1,
                           breaking_headline=_cut(item.headline, 60).upper(), headline=_cut(item.headline, 60).upper(),
                           location=item.location or "INDIA", state=state_name.title() if state_name else "",
                           style="roundup", breaking_image_query=item.image_query,
                           narration=item.narration, theme=theme))
    # ROUNDUP STARTS WITH MAP (no title_card) so hook plays over map
    scenes = [Scene(type="map_intro", country="India", pin="India", overlay_text="INDIA IN LAST 24 HOURS",
                    narration=intro, theme="purple").model_dump()]
    scenes += [sc.model_dump() for sc in built]
    return {"schema": {"scenes": scenes, "caption": caption, "hashtags": hashtags}, "article": state["articles"][0]}

def reply_comments(state):
    if not settings.zernio_api_key: return {}
    try:
        posts = httpx.get(f"{ZERNIO}/posts", params={"limit": 3},
                          headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        post_ids = [p.get("id") or p.get("_id") for p in posts.get("posts", []) if p.get("platform") == "instagram"]
        if not post_ids: return {}
        cr = httpx.get(f"{ZERNIO}/comments", params={"postId": post_ids[0], "limit": 5},
                       headers={"Authorization": f"Bearer {settings.zernio_api_key}"}, timeout=30).json()
        replied = 0
        for c in cr.get("comments", cr.get("data", [])):
            if c.get("isRead") or c.get("isOwner") or replied >= 2: continue
            try:
                reply_resp = llm_create(f"Friendly 1-sentence reply to '{c.get('text','')}' from {c.get('user',{}).get('name','')}. Ask a question back.", CommentReply)
                reply_text = reply_resp.text if hasattr(reply_resp, "text") else str(reply_resp)
                httpx.post(f"{ZERNIO}/comments/{c.get('id') or c.get('_id')}/reply",
                           headers={"Authorization": f"Bearer {settings.zernio_api_key}"},
                           json={"text": reply_text}, timeout=30)
                replied += 1
            except Exception as e: logger.warning(f"reply skipped: {e}")
    except Exception as e: logger.warning(f"reply loop skipped: {e}")