from uuid import UUID

from fastapi import HTTPException, status

from app.api.schemas import (
    ChatMessageListResponse,
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
    UpdateUserRequest,
    UpdateUserResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserDeleteResponse,
    UserListResponse,
    UserResponse,
)
from app.core.database import DatabaseNotConfigured
from app.services.chat_history_service import (
    ChatMessageRecord,
    ChatSessionRecord,
    count_chat_sessions,
    list_chat_messages,
    list_chat_sessions,
    record_chat_exchange,
)
from app.services.chat_service import chat, health
from app.services.user_service import (
    CannotDeleteLastAdmin,
    UserAlreadyExists,
    UserNotFound,
    UserRecord,
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
    result = await chat(
        req.message,
        thread_id=req.thread_id,
        system=req.system,
        user_id=str(user.id),
    )
    history_saved = True
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
        logger.exception("聊天历史保存失败：user_id=%s thread_id=%s", user.id, result.thread_id)

    return ChatResponse(
        reply=result.reply,
        thread_id=result.thread_id,
        tool_calls=result.tool_calls,
        history_saved=history_saved,
    )


async def handle_health() -> dict:
    return await health()


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


async def handle_create_user(req: UserCreateRequest) -> UserCreateResponse:
    try:
        created = await create_user(
            username=req.username,
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
