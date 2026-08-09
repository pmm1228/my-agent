import uuid

from app.api.schemas import ChatRequest, ChatResponse
from app.core.config import get_settings
from app.graph.builder import graph


async def handle_chat(req: ChatRequest) -> ChatResponse:
    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    messages = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.append({"role": "user", "content": req.message})

    result = await graph.ainvoke({"messages": messages}, config)

    tool_calls = []
    reply_content = ""
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            tool_calls.extend(
                [{"name": tc["name"], "args": tc["args"]} for tc in msg.tool_calls]
            )
        if hasattr(msg, "content") and msg.content:
            reply_content = msg.content

    return ChatResponse(reply=reply_content, thread_id=thread_id, tool_calls=tool_calls)


async def handle_health() -> dict:
    s = get_settings()
    return {"status": "ok", "model": s.DEEPSEEK_MODEL}
