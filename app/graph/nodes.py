from app.core.llm import get_llm
from app.graph.prompts import SYSTEM_PROMPT
from app.graph.state import State
from app.tools.registry import all_tools

llm_with_tools = get_llm().bind_tools(all_tools)


def _has_system_message(messages: list) -> bool:
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "system":
            return True
        if getattr(message, "type", None) == "system":
            return True
    return False


def _messages_with_default_system(messages: list) -> list:
    if _has_system_message(messages):
        return messages
    return [{"role": "system", "content": SYSTEM_PROMPT}, *messages]


def chatbot(state: State) -> dict:
    messages = _messages_with_default_system(state["messages"])
    return {"messages": [llm_with_tools.invoke(messages)]}
