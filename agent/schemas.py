from pydantic import BaseModel, Field
from typing import Literal, Optional
from typing import List

class Article(BaseModel):
    title: str; link: str; source: str; published: str = ""

class SelectedStory(BaseModel):
    article_index: int; reason: str; hook_line: str

class Scene(BaseModel):
    type: Literal["title_card", "map_intro", "news_frame", "article_card", "location_highlight",
                   "disaster_dramatic", "footage_highlight", "breaking_card",
                   "quote_card", "stat_overlay", "clip", "map", "article",
                   "quote", "breaking"]
    narration: str = ""
    # title_card / map_intro
    country: Optional[str] = None
    pin: Optional[str] = None
    overlay_text: Optional[str] = None
    theme: Optional[str] = "purple"
    # news_frame
    frame_number: Optional[int] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    style: Optional[str] = None
    state: Optional[str] = None
    # article_card
    masthead: Optional[str] = None
    category: Optional[str] = None
    date_str: Optional[str] = None
    source_color: Optional[str] = "#c00"
    # location_highlight
    # disaster_dramatic
    sub_text: Optional[str] = None
    # footage_highlight
    circle_x: Optional[int] = 540
    circle_y: Optional[int] = 960
    circle_r: Optional[int] = 200
    label_text: Optional[str] = None
    # breaking_card
    breaking_headline: Optional[str] = None
    breaking_sub: Optional[str] = None
    # quote_card
    quote_text: Optional[str] = None
    person: Optional[str] = None
    # stat_overlay
    stat_text: Optional[str] = None
    stat_label: Optional[str] = None
    # clip / shared
    clip_query: Optional[str] = None
    red_circle: bool = False
    # shared media
    image_url: Optional[str] = None
    article_link: Optional[str] = None
    breaking_image_query: Optional[str] = None

class StorySchema(BaseModel):
    scenes: list[Scene] = Field(description="Story scenes in order. Start with title_card hook, then map_intro, then mix of news_frame/article_card/location_highlight/quote_card/stat_overlay/footage_highlight based on story content. End with breaking_card for other headlines.")
    caption: str = ""
    hashtags: list[str] = []

class RoundupScene(BaseModel):
    headline: str = Field(description="Short 5-6 word English ALL CAPS headline")
    narration: str = Field(description="1 quick spoken sentence (Hindi or English based on config) explaining the event")
    image_query: str = Field(description="Visual search query for the background image")
    location: str = Field(description="Location for the story (city/state/country)", default="INDIA")
    state: str = Field(description="Indian state name for map highlight (e.g. Rajasthan, Karnataka). Empty if national/international.", default="")

class RoundupSchema(BaseModel):
    intro_narration: str = Field(description="Hook: e.g., 'आइए जानते हैं भारत में पिछले 24 घंटों में क्या हुआ'")
    scenes: List[RoundupScene] = Field(description="Exactly 8 fast-paced news headlines")
    caption: str
    hashtags: List[str]

class CommentReply(BaseModel):
    text: str = Field(description="The generated reply text")