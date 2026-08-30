from pydantic import BaseModel, Field
from typing import Literal, Optional

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

class StorySchema(BaseModel):
    scenes: list[Scene] = Field(description="Story order: map hook first, then clip/article/quote scenes, end with 1-2 breaking scenes for OTHER headlines")
    caption: str = ""; hashtags: list[str] = []