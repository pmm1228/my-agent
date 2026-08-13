from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import require_user
from app.api.handlers.chat import (
    handle_chat,
    handle_chat_confirmation,
    handle_chat_stream,
    handle_delete_chat_session,
    handle_list_chat_messages,
    handle_list_chat_sessions,
)
from app.api.schemas.chat import (
    ChatConfirmationRequest,
    ChatMessageListResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionDeleteResponse,
    ChatSessionListResponse,
)
from app.services.user_service import UserRecord


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    summary="Agent 对话",
    description=(
        "向 Agent 发送一条消息，返回生成的回复。"
        "当问题需要实时数据（天气、台风等）时，Agent 会自动调用注册的工具。"
        "需要有效的 Authorization Bearer Token。"
    ),
    response_model=ChatResponse,
)
async def chat(
    req: ChatRequest,
    user: UserRecord = Depends(require_user),
) -> ChatResponse:
    return await handle_chat(req, user=user)


@router.post(
    "/confirm",
    summary="确认或拒绝联网",
    description="恢复一个因联网工具调用而暂停的会话。",
    response_model=ChatResponse,
)
async def confirm_chat_web_access(
    req: ChatConfirmationRequest,
    user: UserRecord = Depends(require_user),
) -> ChatResponse:
    return await handle_chat_confirmation(req, user=user)


@router.post(
    "/stream",
    summary="Agent 流式对话",
    description="以 NDJSON 持续返回模型输出；最后一条 done 事件包含会话 ID。",
)
async def stream_chat_response(
    req: ChatRequest,
    user: UserRecord = Depends(require_user),
):
    return await handle_chat_stream(req, user=user)


@router.get(
    "/sessions",
    summary="列出聊天会话",
    description="分页返回当前用户的聊天会话。需要有效的 Authorization Bearer Token。",
    response_model=ChatSessionListResponse,
)
async def list_chat_sessions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: UserRecord = Depends(require_user),
) -> ChatSessionListResponse:
    return await handle_list_chat_sessions(user=user, limit=limit, offset=offset)


@router.get(
    "/sessions/{thread_id}/messages",
    summary="列出聊天消息",
    description="分页返回当前用户某个 thread_id 下的永久聊天消息。",
    response_model=ChatMessageListResponse,
)
async def list_chat_messages(
    thread_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: UserRecord = Depends(require_user),
) -> ChatMessageListResponse:
    return await handle_list_chat_messages(
        user=user,
        thread_id=thread_id,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/sessions/{thread_id}",
    summary="删除聊天会话",
    description="删除当前用户的指定聊天会话、消息及 Agent 上下文。",
    response_model=ChatSessionDeleteResponse,
)
async def delete_chat_session(
    thread_id: str,
    user: UserRecord = Depends(require_user),
) -> ChatSessionDeleteResponse:
    return await handle_delete_chat_session(user=user, thread_id=thread_id)
