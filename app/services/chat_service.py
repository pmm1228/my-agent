import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from app.core.config import get_settings
from app.graph.builder import graph
from app.graph.prompts import SYSTEM_PROMPT


@dataclass(slots=True)
class ChatResult:
    reply: str
    thread_id: str
    tool_calls: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ChatStreamEvent:
    type: Literal["token", "done"]
    content: str = ""
    result: ChatResult | None = None


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


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)

    return ""


def _chat_config(thread_id: str, user_id: str | None) -> dict:
    checkpoint_thread_id = f"user:{user_id}:thread:{thread_id}" if user_id else thread_id
    configurable: dict = {"thread_id": checkpoint_thread_id}
    if user_id:
        configurable["user_id"] = user_id
    return {"configurable": configurable}


def _input_messages(message: str, *, has_history: bool, system: str | None) -> list[dict]:
    messages = []
    if not has_history:
        messages.append({"role": "system", "content": system or SYSTEM_PROMPT})
    messages.append({"role": "user", "content": message})
    return messages


async def chat(
    message: str,
    *,
    thread_id: str | None = None,
    system: str | None = None,
    user_id: str | None = None,
) -> ChatResult:
    thread_id = thread_id or str(uuid.uuid4())
    config = _chat_config(thread_id, user_id)
    has_history, previous_message_count = await _get_thread_history(config)
    result = await graph.ainvoke(
        {"messages": _input_messages(message, has_history=has_history, system=system)},
        config,
    )
    reply, tool_calls = _collect_new_response(
        result["messages"],
        previous_message_count,
    )
    return ChatResult(reply=reply, thread_id=thread_id, tool_calls=tool_calls)


async def stream_chat(
    message: str,
    *,
    thread_id: str | None = None,
    system: str | None = None,
    user_id: str | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    """Yield model text chunks, followed by the completed response metadata."""
    thread_id = thread_id or str(uuid.uuid4())
    config = _chat_config(thread_id, user_id)
    has_history, previous_message_count = await _get_thread_history(config)
    inputs = {"messages": _input_messages(message, has_history=has_history, system=system)}

    async for event in graph.astream_events(inputs, config, version="v2"):
        if event.get("event") != "on_chat_model_stream":
            continue
        if event.get("metadata", {}).get("langgraph_node") != "chatbot":
            continue

        chunk = event.get("data", {}).get("chunk")
        content = _content_to_text(getattr(chunk, "content", ""))
        if content:
            yield ChatStreamEvent(type="token", content=content)

    snapshot = await graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot.values else []
    reply, tool_calls = _collect_new_response(messages, previous_message_count)
    yield ChatStreamEvent(
        type="done",
        result=ChatResult(reply=reply, thread_id=thread_id, tool_calls=tool_calls),
    )


async def close_resources() -> None:
    close = getattr(graph.checkpointer, "aclose", None)
    if close is not None:
        await close()


async def delete_thread_history(*, thread_id: str, user_id: str) -> None:
    checkpoint_thread_id = _chat_config(thread_id, user_id)["configurable"]["thread_id"]
    await graph.checkpointer.adelete_thread(checkpoint_thread_id)


async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "model": settings.DEEPSEEK_MODEL}
