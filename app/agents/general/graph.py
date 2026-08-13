from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from app.agents.contracts import RootState
from app.graph.nodes import chatbot
from app.graph.web_confirmation import tools_with_web_confirmation


def prepare_general_node(_: RootState) -> dict:
    return {
        "route": "general",
        "active_agent": "general",
        "last_agent": "general",
        "handoff": None,
        "agent_status": "running",
    }


def _message_text(message) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else ""


def general_exit_node(state: RootState) -> dict:
    summary = ""
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) in {"ai", "assistant"}:
            summary = _message_text(message)
            break
        if isinstance(message, dict) and message.get("role") == "assistant":
            summary = _message_text(message)
            break
    return {
        "agent_status": "completed",
        "agent_result": {
            "agent": "general",
            "status": "completed",
            "summary": summary,
            "data": {},
            "warnings": [],
            "errors": [],
        },
    }


def route_after_chatbot(state: RootState) -> str:
    return "tools" if tools_condition(state) == "tools" else "exit"


def build_general_graph():
    """Build the general-purpose chat/tool agent as a reusable subgraph."""
    builder = StateGraph(RootState)
    builder.add_node("prepare", prepare_general_node)
    builder.add_node("chatbot", chatbot)
    builder.add_node("tools", tools_with_web_confirmation)
    builder.add_node("exit", general_exit_node)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "chatbot")
    builder.add_conditional_edges(
        "chatbot",
        route_after_chatbot,
        {"tools": "tools", "exit": "exit"},
    )
    builder.add_edge("tools", "chatbot")
    builder.add_edge("exit", END)
    return builder.compile(checkpointer=None, name="general_agent")
