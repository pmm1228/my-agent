from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


ChatMessageRole = Literal["user", "assistant", "system", "tool"]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    thread_id: str | None = None
    system: str | None = None


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    tool_calls: list[dict] = Field(default_factory=list)
    history_saved: bool = True
    status: Literal["completed", "requires_confirmation"] = "completed"
    confirmation: dict | None = None


class ChatConfirmationRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=256)
    approved: bool


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    thread_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    items: list[ChatSessionResponse]
    total: int


class ChatSessionDeleteResponse(BaseModel):
    deleted: bool = True
    thread_id: str


class ChatMessageResponse(BaseModel):
    id: int
    session_id: UUID
    role: ChatMessageRole
    content: str
    tool_calls: list[dict] = Field(default_factory=list)
    created_at: datetime


class ChatMessageListResponse(BaseModel):
    session: ChatSessionResponse
    items: list[ChatMessageResponse]
    total: int

