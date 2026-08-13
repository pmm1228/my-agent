import json

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.schemas.chat import (
    ChatConfirmationRequest,
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionDeleteResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
)
from app.core.conversation_lock import ConversationLockTimeout
from app.core.database import DatabaseNotConfigured
from app.services.chat_history_service import (
    ChatMessageRecord,
    ChatSessionRecord,
    count_chat_sessions,
    delete_chat_session,
    list_chat_messages,
    list_chat_sessions,
    record_chat_exchange,
)
from app.services.chat_service import (
    chat,
    confirm_web_access,
    delete_thread_history,
    stream_chat,
)
from app.services.user_service import UserRecord
from app.utils.logging import get_logger


logger = get_logger(__name__)


def _to_chat_session_response(session: ChatSessionRecord) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        user_id=session.user_id,
        thread_id=session.thread_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _to_chat_message_response(message: ChatMessageRecord) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        tool_calls=message.tool_calls,
        created_at=message.created_at,
    )


async def handle_chat(req: ChatRequest, *, user: UserRecord) -> ChatResponse:
    history_saved = True

    async def save_history(result):
        nonlocal history_saved
        try:
            await record_chat_exchange(
                user_id=user.id,
                thread_id=result.thread_id,
                user_message=req.message,
                assistant_reply=result.reply,
                tool_calls=result.tool_calls,
            )
        except Exception:
            history_saved = False
            logger.exception(
                "聊天历史保存失败：user_id=%s thread_id=%s",
                user.id,
                result.thread_id,
            )

    try:
        result = await chat(
            req.message,
            thread_id=req.thread_id,
            system=req.system,
            user_id=str(user.id),
            on_completed=save_history,
        )
    except ConversationLockTimeout as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前会话正在处理上一条消息，请稍后重试",
        ) from e

    return ChatResponse(
        reply=result.reply,
        thread_id=result.thread_id,
        tool_calls=result.tool_calls,
        history_saved=history_saved,
        status=result.status,
        confirmation=result.confirmation,
    )


async def handle_chat_confirmation(
    req: ChatConfirmationRequest,
    *,
    user: UserRecord,
) -> ChatResponse:
    history_saved = True

    async def save_history(result):
        nonlocal history_saved
        try:
            await record_chat_exchange(
                user_id=user.id,
                thread_id=result.thread_id,
                user_message=result.input_message,
                assistant_reply=result.reply,
                tool_calls=result.tool_calls,
            )
        except Exception:
            history_saved = False
            logger.exception(
                "确认联网后的聊天历史保存失败：user_id=%s thread_id=%s",
                user.id,
                result.thread_id,
            )

    try:
        result = await confirm_web_access(
            thread_id=req.thread_id,
            approved=req.approved,
            user_id=str(user.id),
            on_completed=save_history,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ConversationLockTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前会话正在处理上一条消息，请稍后重试",
        ) from exc

    return ChatResponse(
        reply=result.reply,
        thread_id=result.thread_id,
        tool_calls=result.tool_calls,
        history_saved=history_saved,
        status=result.status,
        confirmation=result.confirmation,
    )


async def handle_chat_stream(req: ChatRequest, *, user: UserRecord) -> StreamingResponse:
    async def generate():
        history_saved = True

        async def save_history(result):
            nonlocal history_saved
            try:
                await record_chat_exchange(
                    user_id=user.id,
                    thread_id=result.thread_id,
                    user_message=req.message,
                    assistant_reply=result.reply,
                    tool_calls=result.tool_calls,
                )
            except Exception:
                history_saved = False
                logger.exception(
                    "聊天历史保存失败：user_id=%s thread_id=%s",
                    user.id,
                    result.thread_id,
                )

        try:
            async for event in stream_chat(
                req.message,
                thread_id=req.thread_id,
                system=req.system,
                user_id=str(user.id),
                on_completed=save_history,
            ):
                if event.type == "token":
                    yield json.dumps(
                        {"type": "token", "content": event.content},
                        ensure_ascii=False,
                    ) + "\n"
                    continue

                result = event.result
                if result is None:
                    continue
                yield json.dumps(
                    {
                        "type": event.type,
                        "reply": result.reply,
                        "thread_id": result.thread_id,
                        "tool_calls": result.tool_calls,
                        "history_saved": history_saved,
                        "status": result.status,
                        "confirmation": result.confirmation,
                    },
                    ensure_ascii=False,
                ) + "\n"
        except ConversationLockTimeout:
            yield json.dumps(
                {
                    "type": "error",
                    "code": "conversation_busy",
                    "message": "当前会话正在处理上一条消息，请稍后重试",
                },
                ensure_ascii=False,
            ) + "\n"
        except Exception:
            logger.exception("流式聊天失败：user_id=%s", user.id)
            yield json.dumps(
                {"type": "error", "message": "生成回复失败，请稍后重试"},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


async def handle_list_chat_sessions(
    *,
    user: UserRecord,
    limit: int = 100,
    offset: int = 0,
) -> ChatSessionListResponse:
    try:
        sessions = await list_chat_sessions(user_id=user.id, limit=limit, offset=offset)
        total = await count_chat_sessions(user_id=user.id)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法读取聊天会话",
        ) from e

    return ChatSessionListResponse(
        items=[_to_chat_session_response(s) for s in sessions],
        total=total,
    )


async def handle_list_chat_messages(
    *,
    user: UserRecord,
    thread_id: str,
    limit: int = 200,
    offset: int = 0,
) -> ChatMessageListResponse:
    try:
        session, messages, total = await list_chat_messages(
            user_id=user.id,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法读取聊天消息",
        ) from e

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="聊天会话不存在",
        )

    return ChatMessageListResponse(
        session=_to_chat_session_response(session),
        items=[_to_chat_message_response(m) for m in messages],
        total=total,
    )


async def handle_delete_chat_session(
    *,
    user: UserRecord,
    thread_id: str,
) -> ChatSessionDeleteResponse:
    async def delete_history() -> bool:
        return await delete_chat_session(user_id=user.id, thread_id=thread_id)

    try:
        deleted = await delete_thread_history(
            thread_id=thread_id,
            user_id=str(user.id),
            delete_persistent_history=delete_history,
        )
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法删除聊天会话",
        ) from e
    except ConversationLockTimeout as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前会话正在处理，暂时无法删除",
        ) from e

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="聊天会话不存在",
        )
    return ChatSessionDeleteResponse(thread_id=thread_id)
