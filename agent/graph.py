from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from . import nodes

class AgentState(TypedDict, total=False):
    articles: list; selected: dict; schema: dict; article: dict
    segments: list; final: str

def build():
    g = StateGraph(AgentState)
    for n, f in [("fetch", nodes.fetch_news), ("select", nodes.select_story),
                 ("schema", nodes.extract_schema), ("scenes", nodes.render_scenes),
                 ("assemble", nodes.assemble), ("publish", nodes.publish)]:
        g.add_node(n, f)
    chain = ["fetch", "select", "schema", "scenes", "assemble", "publish"]
    g.add_edge(START, "fetch")
    for a, b in zip(chain, chain[1:]): g.add_edge(a, b)
    g.add_edge("publish", END)
    return g.compile()