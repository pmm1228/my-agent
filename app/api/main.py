from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, Query

from app.api.auth import require_admin_user, require_user
from app.api.routes import (
    handle_chat,
    handle_create_user,
    handle_delete_user,
    handle_get_me,
    handle_get_user,
    handle_health,
    handle_list_chat_messages,
    handle_list_chat_sessions,
    handle_list_users,
    handle_update_user,
)
from app.api.schemas import (
    ChatMessageListResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionListResponse,
    HealthResponse,
    UpdateUserRequest,
    UpdateUserResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserDeleteResponse,
    UserListResponse,
    UserResponse,
)
from app.core.database import close_database, init_database
from app.services.chat_service import close_resources
from app.services.user_service import UserRecord


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_database()
        yield
    finally:
        await close_database()
        await close_resources()


def create_app() -> FastAPI:
    app = FastAPI(
        title="My-Agent API",
        version="0.1.0",
        lifespan=lifespan,
        description="""
        基于 LangGraph 的可扩展 AI Agent 服务。

        ## 核心能力
        - 🤖 **智能对话**：支持多轮会话、工具自动调用
        - 🌐 **实时工具**：天气查询、台风追踪等可扩展工具集
        - 💾 **会话持久化**：MemorySaver（默认）/ AsyncPostgresSaver（生产）

        ## 会话机制
        不传 `thread_id` 自动创建新会话并返回；
        传入之前的 `thread_id` 则延续上下文。
        """,
        openapi_tags=[
            {"name": "chat", "description": "Agent 对话接口"},
            {"name": "users", "description": "用户与权限管理接口"},
            {"name": "system", "description": "系统管理接口"},
        ],
    )

    @app.get(
        "/health",
        tags=["system"],
        summary="健康检查",
        description="返回服务状态和当前模型名称。部署时可作为 liveness probe。",
        response_model=HealthResponse,
    )
    async def health() -> dict:
        return await handle_health()

    @app.post(
        "/chat",
        tags=["chat"],
        summary="Agent 对话",
        description=(
            "向 Agent 发送一条消息，返回生成的回复。"
            "当问题需要实时数据（天气、台风等）时，Agent 会自动调用注册的工具。"
            "需要有效的 X-API-Key 鉴权。"
        ),
        response_model=ChatResponse,
    )
    async def chat(
        req: ChatRequest,
        user: UserRecord = Depends(require_user),
    ) -> ChatResponse:
        return await handle_chat(req, user=user)

    @app.get(
        "/chat/sessions",
        tags=["chat"],
        summary="列出聊天会话",
        description="分页返回当前用户的聊天会话。需要有效的 X-API-Key。",
        response_model=ChatSessionListResponse,
    )
    async def list_chat_sessions(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        user: UserRecord = Depends(require_user),
    ) -> ChatSessionListResponse:
        return await handle_list_chat_sessions(
            user=user,
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/chat/sessions/{thread_id}/messages",
        tags=["chat"],
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

    @app.post(
        "/users",
        tags=["users"],
        summary="新增用户",
        description="创建一个新用户，返回一次性的明文 API Key。该接口需要管理员权限。",
        response_model=UserCreateResponse,
        status_code=201,
        dependencies=[Depends(require_admin_user)],
    )
    async def create_user(req: UserCreateRequest) -> UserCreateResponse:
        return await handle_create_user(req)

    @app.delete(
        "/users/{user_id}",
        tags=["users"],
        summary="删除用户",
        description="按用户 ID 删除用户记录。该接口需要管理员权限。",
        response_model=UserDeleteResponse,
        dependencies=[Depends(require_admin_user)],
    )
    async def delete_user(user_id: UUID) -> UserDeleteResponse:
        return await handle_delete_user(user_id)

    @app.get(
        "/me",
        tags=["users"],
        summary="获取当前用户",
        description="返回当前 API Key 对应的用户信息。需要有效的 X-API-Key。",
        response_model=UserResponse,
    )
    async def me(user: UserRecord = Depends(require_user)) -> UserResponse:
        return await handle_get_me(user)

    @app.get(
        "/users",
        tags=["users"],
        summary="列出用户",
        description="分页返回所有用户。该接口需要管理员权限。",
        response_model=UserListResponse,
        dependencies=[Depends(require_admin_user)],
    )
    async def list_users(
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> UserListResponse:
        return await handle_list_users(limit=limit, offset=offset)

    @app.get(
        "/users/{user_id}",
        tags=["users"],
        summary="获取用户详情",
        description="按用户 ID 查询用户信息。该接口需要管理员权限。",
        response_model=UserResponse,
        dependencies=[Depends(require_admin_user)],
    )
    async def get_user(user_id: UUID) -> UserResponse:
        return await handle_get_user(user_id)

    @app.patch(
        "/users/{user_id}",
        tags=["users"],
        summary="更新用户",
        description=(
            "更新用户的角色、禁用状态、显示名。"
            "设置 reset_api_key=true 可重置 API Key（新 key 仅在响应中返回一次）。"
            "该接口需要管理员权限。"
        ),
        response_model=UpdateUserResponse,
        dependencies=[Depends(require_admin_user)],
    )
    async def update_user(
        user_id: UUID,
        req: UpdateUserRequest,
    ) -> UpdateUserResponse:
        return await handle_update_user(user_id, req)

    return app


app = create_app()
