import sqlite3

# LangChain / LangGraph
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

# Custom imports 
from .state import AgentState
from .nodes import assistant_node, tool_node, should_continue


# Graph construction
graph = StateGraph(AgentState)

graph.add_node("assistant", assistant_node)
graph.add_node("tools", tool_node)

graph.add_edge(START, "assistant")
graph.add_conditional_edges("assistant", should_continue, ["tools", END])
graph.add_edge("tools", "assistant")

# Persistent checkpointing
conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
memory = SqliteSaver(conn)
agent = graph.compile(checkpointer=memory)