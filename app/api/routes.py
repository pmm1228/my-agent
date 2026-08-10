from app.api.schemas import ChatRequest, ChatResponse
from app.services.chat_service import chat, health


async def handle_chat(req: ChatRequest) -> ChatResponse:
    result = await chat(req.message, thread_id=req.thread_id, system=req.system)
    return ChatResponse(
        reply=result.reply,
        thread_id=result.thread_id,
        tool_calls=result.tool_calls,
    )


async def handle_health() -> dict:
    return await health()
