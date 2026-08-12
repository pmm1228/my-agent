from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


UserRole = Literal["admin", "user"]
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


class HealthResponse(BaseModel):
    status: str
    model: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class UserCreateRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    password: str | None = Field(default=None, min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    role: UserRole = "user"
    api_key: str | None = Field(
        default=None,
        min_length=16,
        max_length=256,
        description="不传则由服务端生成；明文只会在创建响应中返回一次。",
    )
    is_active: bool = True


class UserResponse(BaseModel):
    id: UUID
    username: str
    display_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreateResponse(UserResponse):
    api_key: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class UserDeleteResponse(BaseModel):
    deleted: bool = True
    user: UserResponse


class UpdateUserRequest(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    reset_api_key: bool = False


class UpdateUserResponse(UserResponse):
    api_key: str | None = Field(
        default=None,
        description="仅当请求中 reset_api_key=true 时返回新的明文 API Key。",
    )


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
