from pydantic import BaseModel, Field
from typing import Literal, Optional
from typing import List

class Article(BaseModel):
    title: str; link: str; source: str; published: str = ""

class SelectedStory(BaseModel):
    article_index: int; reason: str; hook_line: str

class Scene(BaseModel):
    type: Literal["map", "clip", "article", "quote", "breaking"]
    narration: str = ""
    # map
    country: Optional[str] = None; pin: Optional[str] = None
    overlay_text: Optional[str] = None
    # clip
    clip_query: Optional[str] = None; stat_text: Optional[str] = None
    red_circle: bool = False
    # article / quote
    masthead: Optional[str] = None; headline: Optional[str] = None
    quote_text: Optional[str] = None; person: Optional[str] = None
    # breaking
    breaking_headline: Optional[str] = None; breaking_sub: Optional[str] = None
    breaking_image_query: Optional[str] = None
    image_url: Optional[str] = None   # real article photo, auto-attached

class StorySchema(BaseModel):
    scenes: list[Scene] = Field(description="Story order: map hook first, then clip/article/quote scenes, end with 1-2 breaking scenes for OTHER headlines")
    caption: str = ""; hashtags: list[str] = []

class RoundupScene(BaseModel):
    headline: str = Field(description="Short 5-6 word English ALL CAPS headline")
    narration: str = Field(description="1 quick spoken sentence (Hindi or English based on config) explaining the event")
    image_query: str = Field(description="Visual search query for the background image")

class RoundupSchema(BaseModel):
    intro_narration: str = Field(description="Hook: e.g., 'आइए जानते हैं भारत में पिछले 24 घंटों में क्या हुआ'")
    scenes: List[RoundupScene] = Field(description="Exactly 8 fast-paced news headlines")
    caption: str
    hashtags: List[str]

# Add to the bottom of agent/schemas.py

class RoundupScene(BaseModel):
    headline: str = Field(description="Short 5-6 word English ALL CAPS headline")
    narration: str = Field(description="1 quick spoken sentence explaining the event")
    image_query: str = Field(description="Visual search query for the background image")

class RoundupSchema(BaseModel):
    intro_narration: str = Field(description="Hook: e.g., 'आइए जानते हैं भारत में पिछले 24 घंटों में क्या हुआ'")
    scenes: list[RoundupScene] = Field(description="Exactly 8 fast-paced news headlines")
    caption: str
    hashtags: list[str]

class CommentReply(BaseModel):
    text: str = Field(description="The generated reply text")