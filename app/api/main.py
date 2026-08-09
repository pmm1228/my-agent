from fastapi import FastAPI

from app.api.routes import handle_chat, handle_health
from app.api.schemas import ChatRequest, ChatResponse, HealthResponse


def create_app() -> FastAPI:
    app = FastAPI(title="My-Agent API", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> dict:
        return await handle_health()

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        return await handle_chat(req)

    return app


app = create_app()
