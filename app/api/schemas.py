from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    thread_id: str | None = None
    system: str | None = None


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    tool_calls: list[dict] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    model: str
