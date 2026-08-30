from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from . import nodes

class AgentState(TypedDict, total=False):
    articles: list; selected: dict; schema: dict; article: dict
    segments: list; final: str; reel_format: str

def build():
    g = StateGraph(AgentState)
    
    # Add all nodes
    g.add_node("fetch", nodes.fetch_news)
    g.add_node("learn", nodes.learn)
    g.add_node("format", nodes.select_format)
    g.add_node("select", nodes.select_story)         # Deep dive path
    g.add_node("select_roundup", nodes.extract_roundup) # Roundup path
    g.add_node("schema", nodes.extract_schema)
    g.add_node("scenes", nodes.render_scenes)
    g.add_node("assemble", nodes.assemble)
    g.add_node("publish", nodes.publish)
    g.add_node("reply", nodes.reply_comments)
    
    # Edges
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "learn")
    g.add_edge("learn", "format")
    
    # Conditional routing based on time of day
    g.add_conditional_edges("format", 
        lambda state: state.get("reel_format", "deep_dive"),
        {"deep_dive": "select", "roundup": "select_roundup"}
    )
    
    g.add_edge("select", "schema")
    # Roundup already extracts schema directly, so it goes straight to rendering
    g.add_edge("select_roundup", "scenes") 
    g.add_edge("schema", "scenes")
    
    g.add_edge("scenes", "assemble")
    g.add_edge("assemble", "publish")
    g.add_edge("publish", "reply")
    g.add_edge("reply", END)
    
    return g.compile()