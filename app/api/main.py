from fastapi import FastAPI

from app.api.routes import handle_chat, handle_health
from app.api.schemas import ChatRequest, ChatResponse, HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(
        title="My-Agent API",
        version="0.1.0",
        description="""
        基于 LangGraph 的可扩展 AI Agent 服务。

        ## 核心能力
        - 🤖 **智能对话**：支持多轮会话、工具自动调用
        - 🌐 **实时工具**：天气查询、台风追踪等可扩展工具集
        - 💾 **会话持久化**：MemorySaver（默认）/ PostgresSaver（生产）

        ## 会话机制
        不传 `thread_id` 自动创建新会话并返回；
        传入之前的 `thread_id` 则延续上下文。
        """,
        openapi_tags=[
            {"name": "chat", "description": "Agent 对话接口"},
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
        ),
        response_model=ChatResponse,
    )
    async def chat(req: ChatRequest) -> ChatResponse:
        return await handle_chat(req)

    return app


app = create_app()
