import json
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatConfirmationRequest,
    ChatRequest,
    ChatResponse,
    ChatSessionDeleteResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
    LoginRequest,
    LoginResponse,
    UpdateUserRequest,
    UpdateUserResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserDeleteResponse,
    UserListResponse,
    UserResponse,
)
from app.core.config import get_settings
from app.core.conversation_lock import ConversationLockTimeout
from app.core.database import DatabaseNotConfigured
from app.core.security import create_access_token
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
    health,
    stream_chat,
)
from app.services.user_service import (
    CannotDeleteLastAdmin,
    UserAlreadyExists,
    UserNotFound,
    UserRecord,
    authenticate_user,
    count_users,
    create_user,
    delete_user,
    get_user_by_id,
    list_users,
    update_user,
)
from app.utils.logging import get_logger


logger = get_logger(__name__)


def _to_user_response(user: UserRecord) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


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
                    yield json.dumps({"type": "token", "content": event.content}, ensure_ascii=False) + "\n"
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
            yield json.dumps({"type": "error", "message": "生成回复失败，请稍后重试"}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


async def handle_health() -> dict:
    return await health()


async def handle_login(req: LoginRequest) -> LoginResponse:
    try:
        user = await authenticate_user(req.username.strip(), req.password)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法登录",
        ) from e
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用",
        )

    settings = get_settings()
    expires_in = max(settings.JWT_EXPIRE_MINUTES, 1) * 60
    access_token = create_access_token(
        subject=str(user.id),
        secret=settings.JWT_SECRET,
        expires_in_seconds=expires_in,
        extra={
            "username": user.username,
            "role": user.role,
        },
    )

    return LoginResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=_to_user_response(user),
    )


async def handle_list_chat_sessions(
    *,
    user: UserRecord,
    limit: int = 100,
    offset: int = 0,
) -> ChatSessionListResponse:
    try:
        sessions = await list_chat_sessions(
            user_id=user.id,
            limit=limit,
            offset=offset,
        )
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


async def handle_create_user(req: UserCreateRequest) -> UserCreateResponse:
    try:
        created = await create_user(
            username=req.username,
            password=req.password,
            role=req.role,
            display_name=req.display_name,
            api_key=req.api_key,
            is_active=req.is_active,
        )
    except UserAlreadyExists as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法创建用户",
        ) from e

    user = _to_user_response(created.user)
    return UserCreateResponse(**user.model_dump(), api_key=created.api_key)


async def handle_delete_user(user_id: UUID) -> UserDeleteResponse:
    try:
        user = await delete_user(user_id)
    except CannotDeleteLastAdmin as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except UserNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法删除用户",
        ) from e

    return UserDeleteResponse(user=_to_user_response(user))


async def handle_get_me(user: UserRecord) -> UserResponse:
    return _to_user_response(user)


async def handle_list_users(*, limit: int = 100, offset: int = 0) -> UserListResponse:
    try:
        users = await list_users(limit=limit, offset=offset)
        total = await count_users()
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置",
        ) from e

    return UserListResponse(
        items=[_to_user_response(u) for u in users],
        total=total,
    )


async def handle_get_user(user_id: UUID) -> UserResponse:
    try:
        user = await get_user_by_id(user_id)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置",
        ) from e

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    return _to_user_response(user)


async def handle_update_user(user_id: UUID, req: UpdateUserRequest) -> UpdateUserResponse:
    try:
        updated = await update_user(
            user_id,
            role=req.role,
            is_active=req.is_active,
            display_name=req.display_name,
            update_display_name="display_name" in req.model_fields_set,
            password=req.password,
            reset_api_key=req.reset_api_key,
        )
    except CannotDeleteLastAdmin as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except UserNotFound as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置",
        ) from e

    user_resp = _to_user_response(updated.user)
    data = user_resp.model_dump()
    data["api_key"] = updated.api_key
    return UpdateUserResponse(**data)
