from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from . import nodes

class AgentState(TypedDict, total=False):
    articles: list; selected: dict; schema: dict; article: dict
    _scraped: dict
    segments: list; final: str; reel_format: str

def build():
    g = StateGraph(AgentState)
    g.add_node("fetch", nodes.fetch_news)
    g.add_node("learn", nodes.learn)
    g.add_node("format", nodes.select_format)
    g.add_node("select", nodes.select_story)
    g.add_node("select_roundup", nodes.extract_roundup)
    g.add_node("schema", nodes.extract_schema)
    g.add_node("proofread", nodes.proofread_schema)
    g.add_node("scenes", nodes.render_scenes)
    g.add_node("assemble", nodes.assemble)
    g.add_node("publish", nodes.publish)
    g.add_node("reply", nodes.reply_comments)
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "learn")
    g.add_edge("learn", "format")
    g.add_conditional_edges("format",
        lambda state: state.get("reel_format", "deep_dive"),
        {"deep_dive": "select", "roundup": "select_roundup"})
    g.add_edge("select", "schema")
    g.add_edge("select_roundup", "proofread")
    g.add_edge("schema", "proofread")
    g.add_edge("proofread", "scenes")
    g.add_edge("scenes", "assemble")
    g.add_edge("assemble", "publish")
    g.add_edge("publish", "reply")
    g.add_edge("reply", END)
    return g.compile()