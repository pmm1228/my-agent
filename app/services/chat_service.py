import uuid
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import AsyncIterator, Literal

from langgraph.types import Command

from app.agents.contracts import CURRENT_STATE_SCHEMA_VERSION
from app.core.config import get_settings
from app.core.conversation_lock import conversation_locks
from app.graph.prompts import SYSTEM_PROMPT
from app.utils.logging import get_logger


@dataclass(slots=True)
class ChatResult:
    reply: str
    thread_id: str
    tool_calls: list[dict] = field(default_factory=list)
    status: Literal["completed", "requires_confirmation"] = "completed"
    confirmation: dict | None = None
    input_message: str = ""


@dataclass(slots=True)
class ChatStreamEvent:
    type: Literal["token", "confirmation", "done"]
    content: str = ""
    result: ChatResult | None = None


ChatCompletedCallback = Callable[[ChatResult], Awaitable[None]]
StateResetCallback = Callable[[str], Awaitable[bool]]
_chat_graph = None
logger = get_logger(__name__)


class AgentConflictError(ValueError):
    """Machine-readable conflict shared by HTTP and streaming transports."""

    def __init__(self, *, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {
            "type": "error",
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class PendingConfirmationError(AgentConflictError):
    """Raised when a new turn would replace an interrupted confirmation flow."""

    def __init__(self, confirmation: dict):
        super().__init__(
            code="pending_confirmation",
            message="当前会话有待确认的联网请求，请先确认或拒绝后再发送新消息",
            details={"confirmation": confirmation},
        )
        self.confirmation = confirmation


class WorkflowResetRequiredError(AgentConflictError):
    """Raised after an incompatible checkpoint has been safely discarded."""

    def __init__(self, *, history_cleared: bool = False):
        super().__init__(
            code="workflow_reset_required",
            message="工作流状态已升级，旧会话状态已清除，请重新发送完整需求",
            details={"checkpoint_cleared": True, "history_cleared": history_cleared},
        )


def get_chat_graph():
    """Return the process-wide compiled graph, imported only when first used."""
    global _chat_graph

    if _chat_graph is not None:
        return _chat_graph

    from app.graph.builder import graph

    _chat_graph = graph
    return _chat_graph


async def _clear_incompatible_state(
    *,
    graph,
    config: dict,
    thread_id: str,
    on_state_reset: StateResetCallback | None,
) -> None:
    await graph.checkpointer.adelete_thread(_checkpoint_thread_id(config))
    history_cleared = False
    if on_state_reset is not None:
        try:
            history_cleared = await on_state_reset(thread_id)
        except Exception:
            logger.exception("清理不兼容业务聊天历史失败：thread_id=%s", thread_id)
    raise WorkflowResetRequiredError(history_cleared=history_cleared)


async def _get_thread_history(
    config: dict,
    *,
    thread_id: str,
    on_state_reset: StateResetCallback | None,
) -> tuple[bool, int]:
    graph = get_chat_graph()
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    messages = values.get("messages", [])
    if messages and values.get("state_schema_version") != CURRENT_STATE_SCHEMA_VERSION:
        await _clear_incompatible_state(
            graph=graph,
            config=config,
            thread_id=thread_id,
            on_state_reset=on_state_reset,
        )
    confirmation = _pending_confirmation(snapshot)
    if confirmation is not None:
        raise PendingConfirmationError(confirmation)
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


def _pending_confirmation(snapshot) -> dict | None:
    interrupts = getattr(snapshot, "interrupts", ())
    if not interrupts:
        return None
    value = getattr(interrupts[0], "value", None)
    return value if isinstance(value, dict) else {"message": str(value)}


def _latest_user_turn(messages: list) -> tuple[int, str]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        message_type = getattr(message, "type", None)
        if message_type in {"human", "user"}:
            return index, _content_to_text(getattr(message, "content", ""))
        if isinstance(message, dict) and message.get("role") == "user":
            return index, _content_to_text(message.get("content", ""))
    return 0, ""


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


def _checkpoint_thread_id(config: dict) -> str:
    return config["configurable"]["thread_id"]


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
    on_completed: ChatCompletedCallback | None = None,
    on_state_reset: StateResetCallback | None = None,
) -> ChatResult:
    thread_id = thread_id or str(uuid.uuid4())
    config = _chat_config(thread_id, user_id)
    async with conversation_locks.acquire(_checkpoint_thread_id(config)):
        graph = get_chat_graph()
        has_history, previous_message_count = await _get_thread_history(
            config,
            thread_id=thread_id,
            on_state_reset=on_state_reset,
        )
        result = await graph.ainvoke(
            {
                "messages": _input_messages(message, has_history=has_history, system=system),
                "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
            },
            config,
        )
        reply, tool_calls = _collect_new_response(
            result["messages"],
            previous_message_count,
        )
        snapshot = await graph.aget_state(config)
        confirmation = _pending_confirmation(snapshot)
        chat_result = ChatResult(
            reply=reply,
            thread_id=thread_id,
            tool_calls=tool_calls,
            status="requires_confirmation" if confirmation else "completed",
            confirmation=confirmation,
            input_message=message,
        )
        if confirmation is None and on_completed is not None:
            await on_completed(chat_result)
    return chat_result


async def stream_chat(
    message: str,
    *,
    thread_id: str | None = None,
    system: str | None = None,
    user_id: str | None = None,
    on_completed: ChatCompletedCallback | None = None,
    on_state_reset: StateResetCallback | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    """Yield model text chunks, followed by the completed response metadata."""
    thread_id = thread_id or str(uuid.uuid4())
    config = _chat_config(thread_id, user_id)
    async with conversation_locks.acquire(_checkpoint_thread_id(config)):
        graph = get_chat_graph()
        has_history, previous_message_count = await _get_thread_history(
            config,
            thread_id=thread_id,
            on_state_reset=on_state_reset,
        )
        inputs = {
            "messages": _input_messages(message, has_history=has_history, system=system),
            "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
        }

        async for event in graph.astream_events(inputs, config, version="v2"):
            if event.get("event") != "on_chat_model_stream":
                continue
            if event.get("metadata", {}).get("langgraph_node") not in {
                "coordinator",
                "chatbot",  # Compatibility with lightweight test/fake graphs.
            }:
                continue

            chunk = event.get("data", {}).get("chunk")
            content = _content_to_text(getattr(chunk, "content", ""))
            if content:
                yield ChatStreamEvent(type="token", content=content)

        snapshot = await graph.aget_state(config)
        messages = snapshot.values.get("messages", []) if snapshot.values else []
        reply, tool_calls = _collect_new_response(messages, previous_message_count)
        confirmation = _pending_confirmation(snapshot)
        chat_result = ChatResult(
            reply=reply,
            thread_id=thread_id,
            tool_calls=tool_calls,
            status="requires_confirmation" if confirmation else "completed",
            confirmation=confirmation,
            input_message=message,
        )
        if confirmation is None and on_completed is not None:
            await on_completed(chat_result)

    yield ChatStreamEvent(
        type="confirmation" if chat_result.confirmation else "done",
        result=chat_result,
    )


async def confirm_web_access(
    *,
    thread_id: str,
    approved: bool,
    user_id: str | None = None,
    on_completed: ChatCompletedCallback | None = None,
    on_state_reset: StateResetCallback | None = None,
) -> ChatResult:
    """Resume a graph paused before web access with the user's decision."""
    config = _chat_config(thread_id, user_id)
    async with conversation_locks.acquire(_checkpoint_thread_id(config)):
        graph = get_chat_graph()
        snapshot = await graph.aget_state(config)
        values = snapshot.values or {}
        if (
            values.get("messages")
            and values.get("state_schema_version") != CURRENT_STATE_SCHEMA_VERSION
        ):
            await _clear_incompatible_state(
                graph=graph,
                config=config,
                thread_id=thread_id,
                on_state_reset=on_state_reset,
            )
        if _pending_confirmation(snapshot) is None:
            raise ValueError("当前会话没有待确认的联网请求")
        existing_messages = snapshot.values.get("messages", [])
        turn_start, input_message = _latest_user_turn(existing_messages)
        result = await graph.ainvoke(Command(resume=approved), config)
        reply, tool_calls = _collect_new_response(result["messages"], turn_start)
        resumed_snapshot = await graph.aget_state(config)
        confirmation = _pending_confirmation(resumed_snapshot)
        chat_result = ChatResult(
            reply=reply,
            thread_id=thread_id,
            tool_calls=tool_calls,
            status="requires_confirmation" if confirmation else "completed",
            confirmation=confirmation,
            input_message=input_message,
        )
        if confirmation is None and on_completed is not None:
            await on_completed(chat_result)
        return chat_result


async def close_resources() -> None:
    if _chat_graph is not None:
        close = getattr(_chat_graph.checkpointer, "aclose", None)
        if close is not None:
            await close()


async def delete_thread_history(
    *,
    thread_id: str,
    user_id: str,
    delete_persistent_history: Callable[[], Awaitable[bool]] | None = None,
) -> bool:
    config = _chat_config(thread_id, user_id)
    checkpoint_thread_id = _checkpoint_thread_id(config)
    async with conversation_locks.acquire(checkpoint_thread_id):
        graph = get_chat_graph()
        deleted = True
        if delete_persistent_history is not None:
            deleted = await delete_persistent_history()
        await graph.checkpointer.adelete_thread(checkpoint_thread_id)
        return deleted


async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "model": settings.DEEPSEEK_MODEL}
