from langchain_core.messages import RemoveMessage

from app.agents.contracts import RootState


COORDINATOR_MESSAGE_NAME = "coordinator"
GENERAL_HANDLER_NAME = "general"


def message_text(message) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else ""


def latest_user_text(state: RootState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, dict) and message.get("role") == "user":
            return message_text(message)
        if getattr(message, "type", None) in {"human", "user"}:
            return message_text(message)
    return ""


def child_message_removals(state: RootState) -> list[RemoveMessage]:
    """Remove child-internal messages from the root transcript before publishing."""
    messages = state.get("messages", [])
    latest_user_index = -1
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if (
            isinstance(message, dict) and message.get("role") == "user"
        ) or getattr(message, "type", None) in {"human", "user"}:
            latest_user_index = index
            break

    removals = []
    for message in messages[latest_user_index + 1:]:
        message_id = getattr(message, "id", None)
        if message_id and getattr(message, "name", None) != COORDINATOR_MESSAGE_NAME:
            removals.append(RemoveMessage(id=message_id))
    return removals
