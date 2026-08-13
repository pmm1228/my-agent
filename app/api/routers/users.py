from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies.auth import require_admin_user, require_user
from app.api.handlers.users import (
    handle_create_user,
    handle_delete_user,
    handle_get_me,
    handle_get_user,
    handle_list_users,
    handle_update_user,
)
from app.api.schemas.users import (
    UpdateUserRequest,
    UpdateUserResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserDeleteResponse,
    UserListResponse,
    UserResponse,
)
from app.services.user_service import UserRecord


router = APIRouter(tags=["users"])


@router.post(
    "/users",
    summary="新增用户",
    description="创建一个新用户。该接口需要管理员权限。",
    response_model=UserCreateResponse,
    status_code=201,
    dependencies=[Depends(require_admin_user)],
)
async def create_user(req: UserCreateRequest) -> UserCreateResponse:
    return await handle_create_user(req)


@router.delete(
    "/users/{user_id}",
    summary="删除用户",
    description="按用户 ID 删除用户记录。该接口需要管理员权限。",
    response_model=UserDeleteResponse,
    dependencies=[Depends(require_admin_user)],
)
async def delete_user(user_id: UUID) -> UserDeleteResponse:
    return await handle_delete_user(user_id)


@router.get(
    "/me",
    summary="获取当前用户",
    description="返回当前 Bearer Token 对应的用户信息。",
    response_model=UserResponse,
)
async def me(user: UserRecord = Depends(require_user)) -> UserResponse:
    return await handle_get_me(user)


@router.get(
    "/users",
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


@router.get(
    "/users/{user_id}",
    summary="获取用户详情",
    description="按用户 ID 查询用户信息。该接口需要管理员权限。",
    response_model=UserResponse,
    dependencies=[Depends(require_admin_user)],
)
async def get_user(user_id: UUID) -> UserResponse:
    return await handle_get_user(user_id)


@router.patch(
    "/users/{user_id}",
    summary="更新用户",
    description=(
        "更新用户的角色、禁用状态、显示名、密码。"
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
