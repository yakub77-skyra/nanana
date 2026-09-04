from pydantic import BaseModel, Field
from typing import Literal, Optional, List

class Article(BaseModel):
    title: str; link: str; source: str; published: str = ""

class SelectedStory(BaseModel):
    article_index: int; reason: str; hook_line: str

class Scene(BaseModel):
    type: Literal["title_card", "map_intro", "news_frame", "article_card", "location_highlight",
                  "disaster_dramatic", "footage_highlight", "breaking_card", "quote_card",
                  "stat_overlay", "stat_callout", "keyword_text", "table_card",
                  "clip", "map", "article", "quote", "breaking"]
    narration: str = ""
    country: Optional[str] = None
    pin: Optional[str] = None
    overlay_text: Optional[str] = None
    theme: Optional[str] = "purple"
    frame_number: Optional[int] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    style: Optional[str] = None
    state: Optional[str] = None
    masthead: Optional[str] = None
    category: Optional[str] = None
    date_str: Optional[str] = None
    source_color: Optional[str] = "#111"
    sub_text: Optional[str] = None
    circle_x: Optional[int] = 540
    circle_y: Optional[int] = 960
    circle_r: Optional[int] = 200
    label_text: Optional[str] = None
    breaking_headline: Optional[str] = None
    breaking_sub: Optional[str] = None
    quote_text: Optional[str] = None
    person: Optional[str] = None
    stat_text: Optional[str] = None
    stat_label: Optional[str] = None
    extra_lines: Optional[List[str]] = None
    keyword: Optional[str] = None
    table_title: Optional[str] = None
    table_rows: Optional[List[List[str]]] = None
    clip_query: Optional[str] = None
    red_circle: bool = False
    image_url: Optional[str] = None
    article_link: Optional[str] = None
    breaking_image_query: Optional[str] = None

class StorySchema(BaseModel):
    scenes: list[Scene] = Field(description="8-12 beats: title_card, map_intro(pin), news_frame, article_card, keyword_text, stat_callout, quote_card, table_card, breaking_card")
    caption: str = ""
    hashtags: list[str] = []

class RoundupScene(BaseModel):
    headline: str = Field(description="Short 5-6 word English ALL CAPS headline")
    narration: str = Field(description="1 quick spoken Hinglish sentence")
    image_query: str = Field(description="Generic visual search query")
    location: str = "INDIA"
    state: str = ""

class RoundupSchema(BaseModel):
    intro_narration: str = "आइए जानते हैं भारत में पिछले 24 घंटों में क्या हुआ"
    scenes: List[RoundupScene] = Field(description="Exactly 8 fast-paced news headlines")
    caption: str
    hashtags: List[str]

class CommentReply(BaseModel):
    text: str