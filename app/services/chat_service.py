import uuid
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.graph.builder import graph
from app.graph.prompts import SYSTEM_PROMPT


@dataclass(slots=True)
class ChatResult:
    reply: str
    thread_id: str
    tool_calls: list[dict] = field(default_factory=list)


async def _get_thread_history(config: dict) -> tuple[bool, int]:
    snapshot = await graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot.values else []
    return bool(messages), len(messages)


def _collect_new_response(messages: list, previous_message_count: int) -> tuple[str, list[dict]]:
    tool_calls = []
    reply_content = ""

    for msg in messages[previous_message_count:]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_calls.extend(
                [{"name": tc["name"], "args": tc["args"]} for tc in msg.tool_calls]
            )
        if hasattr(msg, "content") and msg.content:
            reply_content = msg.content

    return reply_content, tool_calls


async def chat(
    message: str,
    *,
    thread_id: str | None = None,
    system: str | None = None,
    user_id: str | None = None,
) -> ChatResult:
    thread_id = thread_id or str(uuid.uuid4())
    checkpoint_thread_id = f"user:{user_id}:thread:{thread_id}" if user_id else thread_id
    configurable: dict = {"thread_id": checkpoint_thread_id}
    if user_id:
        configurable["user_id"] = user_id
    config = {"configurable": configurable}
    has_history, previous_message_count = await _get_thread_history(config)

    messages = []
    if not has_history:
        messages.append({"role": "system", "content": system or SYSTEM_PROMPT})
    messages.append({"role": "user", "content": message})

    result = await graph.ainvoke({"messages": messages}, config)
    reply, tool_calls = _collect_new_response(
        result["messages"],
        previous_message_count,
    )
    return ChatResult(reply=reply, thread_id=thread_id, tool_calls=tool_calls)


async def close_resources() -> None:
    close = getattr(graph.checkpointer, "aclose", None)
    if close is not None:
        await close()


async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "model": settings.DEEPSEEK_MODEL}
