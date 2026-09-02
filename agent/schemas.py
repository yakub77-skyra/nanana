
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field

class Scene(BaseModel):
    type: str = Field(..., description="Scene type: intro_marquee, map_intro, news_frame, article_card, location_highlight, disaster_dramatic, footage_highlight, breaking_card, quote_card, stat_overlay, outro")
    duration: float = Field(default=5.0, ge=0.5)
    
    # Text content
    text: Optional[str] = None
    headline: Optional[str] = None
    sub_text: Optional[str] = None
    quote_text: Optional[str] = None
    quote_person: Optional[str] = None
    stat_text: Optional[str] = None
    stat_label: Optional[str] = None
    
    # Location / country
    country: Optional[str] = None
    location: Optional[str] = None
    
    # Media
    image_url: Optional[str] = None
    photo_path: Optional[str] = None
    bg_path: Optional[str] = None
    footage_path: Optional[str] = None
    topic_img_path: Optional[str] = None
    
    # For numbered news frames
    number: Optional[int] = None
    
    # For highlight circles
    circle_x: Optional[int] = None
    circle_y: Optional[int] = None
    circle_radius: Optional[int] = None
    label_text: Optional[str] = None
    
    # For article card
    masthead: Optional[str] = None
    category: Optional[str] = None
    date_str: Optional[str] = None
    source_color: Optional[str] = None
    
    # For breaking card
    source: Optional[str] = None
    
    # For map intro
    pin: Optional[str] = None
    overlay_text: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    
    # Theme
    theme: str = "purple"
    
    # News article references
    breaking_headline: Optional[str] = None
    breaking_image_query: Optional[str] = None
    article_link: Optional[str] = None
    
    # Legacy
    clip_query: Optional[str] = None

class Script(BaseModel):
    scenes: List[Scene] = Field(default_factory=list)
    music_query: Optional[str] = None
    voiceover_text: Optional[str] = None
    format: str = "deep_dive"  # "deep_dive" or "roundup"
    topic: Optional[str] = None
    total_duration: float = 0.0

class NewsItem(BaseModel):
    headline: str
    location: Optional[str] = None
    image_query: Optional[str] = None
    article_link: Optional[str] = None

class RoundupScript(BaseModel):
    intro_teaser: Optional[str] = None
    items: List[NewsItem] = Field(default_factory=list)
    outro: bool = True
