from typing import List
from .schemas import Scene, Script, NewsItem, RoundupScript
from . import scraper, media
from .config import settings

def fetch_news(state: dict) -> dict:
    articles = scraper.latest_news()
    if not articles:
        articles = [{"title": "India News Update", "url": "", "source": "NewsAPI"}]
    state["articles"] = articles
    return state

def choose_topic(state: dict) -> dict:
    articles = state.get("articles", [])
    topic = state.get("topic")
    if not topic and articles:
        topic = articles[0]["title"]
    state["topic"] = topic
    return state

def extract_deep_dive(state: dict) -> dict:
    articles = state.get("articles", [])
    topic = state.get("topic", "India News")
    article = next((a for a in articles if topic.lower() in a.get("title", "").lower()), articles[0] if articles else {})
    
    headline = article.get("title", topic)
    source = article.get("source", {}).get("name", "NEWS")
    location = "India"
    url = article.get("url", "")
    img_url = article.get("urlToImage", "")
    summary = article.get("description", "") or headline
    
    scenes = [
        Scene(type="map_intro", duration=4, country="India", overlay_text=headline, headline=headline, theme="purple"),
        Scene(type="article_card", duration=4, masthead=source, headline=headline, category="NEWS", image_url=img_url, article_link=url, theme="purple"),
        Scene(type="location_highlight", duration=4, country="India", location=location, headline=headline, image_url=img_url, article_link=url, theme="purple"),
        Scene(type="disaster_dramatic", duration=4, headline=headline, sub_text=summary, image_url=img_url, article_link=url, theme="red"),
        Scene(type="footage_highlight", duration=4, headline=headline, image_url=img_url, article_link=url, circle_x=540, circle_y=960, circle_radius=200, label_text=location),
        Scene(type="breaking_card", duration=4, headline=headline, sub_text=summary, image_url=img_url, article_link=url, source=source),
        Scene(type="quote_card", duration=4, quote_text=summary, quote_person=source, theme="purple"),
        Scene(type="stat_overlay", duration=4, stat_text="24", stat_label="HOURS", image_url=img_url, article_link=url, theme="purple"),
        Scene(type="outro", duration=4),
    ]
    
    state["script"] = Script(scenes=scenes, format="deep_dive", topic=topic)
    return state

def extract_roundup(state: dict) -> dict:
    articles = state.get("articles", [])
    topic = state.get("topic", "India News")
    
    # Build 8 headline items
    items: List[NewsItem] = []
    for i, a in enumerate(articles[:8]):
        headline = a.get("title", f"News {i+1}")
        # Extract location from headline or default to India
        location = "INDIA"
        loc_patterns = ["Delhi", "Mumbai", "Bangalore", "Chennai", "Kolkata", "Hyderabad", 
                       "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Kerala", "Tamil Nadu", 
                       "Karnataka", "Maharashtra", "Gujarat", "Rajasthan", "Uttar Pradesh",
                       "Goa", "Ayodhya", "Andhra Pradesh", "Multiple States"]
        for pat in loc_patterns:
            if pat.upper() in headline.upper():
                location = pat.upper()
                break
        
        img_query = headline
        url = a.get("url", "")
        items.append(NewsItem(headline=headline, location=location, image_query=img_query, article_link=url))
    
    # If we don't have 8 articles, fill with generic headlines
    while len(items) < 8:
        items.append(NewsItem(headline=f"India News Update {len(items)+1}", location="INDIA", image_query="India news"))
    
    # Build intro teaser from the most "viral" sounding headline (or first)
    intro_teaser = items[0].headline if items else "INDIA IN LAST 24 HOURS"
    
    scenes = []
    
    # 1. INTRO MARQUEE — scrolling text teaser (matches reel_final.mp4 intro)
    scenes.append(Scene(
        type="intro_marquee",
        duration=3.5,
        text=intro_teaser,
        theme="purple"
    ))
    
    # 2-9. NUMBERED NEWS FRAMES — pure black background (matches reel_final.mp4)
    for idx, item in enumerate(items[:8], start=1):
        scenes.append(Scene(
            type="news_frame",
            duration=4.5,
            number=idx,
            headline=item.headline,
            breaking_headline=item.headline,
            breaking_image_query=item.image_query,
            article_link=item.article_link,
            clip_query=item.image_query,  # ensures image download works
            location=item.location,
            theme="purple"
        ))
    
    # 10. OUTRO — Instagram follow card
    scenes.append(Scene(
        type="outro",
        duration=4
    ))
    
    total_dur = sum(s.duration for s in scenes)
    state["script"] = Script(
        scenes=scenes,
        format="roundup",
        topic=topic,
        total_duration=total_dur
    )
    return state

def generate_voiceover(state: dict) -> dict:
    script = state.get("script")
    if not script:
        return state
    
    if script.format == "roundup":
        lines = [f"Headline {s.number}: {s.headline}" for s in script.scenes if s.type == "news_frame"]
        text = ". ".join(lines)
    else:
        text = " ".join(s.headline or s.text or "" for s in script.scenes if s.headline or s.text)
    
    script.voiceover_text = text
    state["script"] = script
    return state

def generate_music_query(state: dict) -> dict:
    script = state.get("script")
    if not script:
        return state
    
    if script.format == "roundup":
        script.music_query = "epic cinematic background music dramatic intense"
    else:
        topic = state.get("topic", "news")
        script.music_query = f"{topic} dramatic background music cinematic"
    
    state["script"] = script
    return state