from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, chat, system, users
from app.core.database import close_database, init_database
from app.services.chat_service import close_resources


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
            {"name": "auth", "description": "登录与身份认证接口"},
            {"name": "chat", "description": "Agent 对话接口"},
            {"name": "users", "description": "用户与权限管理接口"},
            {"name": "system", "description": "系统管理接口"},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(users.router)
    return app


app = create_app()
