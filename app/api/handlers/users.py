from uuid import UUID

from fastapi import HTTPException, status

from app.api.mappers import to_user_response
from app.api.schemas.users import (
    UpdateUserRequest,
    UpdateUserResponse,
    UserCreateRequest,
    UserCreateResponse,
    UserDeleteResponse,
    UserListResponse,
    UserResponse,
)
from app.core.database import DatabaseNotConfigured
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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法创建用户",
        ) from e

    user = to_user_response(created.user)
    return UserCreateResponse(**user.model_dump(), api_key=created.api_key)


async def handle_delete_user(user_id: UUID) -> UserDeleteResponse:
    try:
        user = await delete_user(user_id)
    except CannotDeleteLastAdmin as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except UserNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法删除用户",
        ) from e

    return UserDeleteResponse(user=to_user_response(user))


async def handle_get_me(user: UserRecord) -> UserResponse:
    return to_user_response(user)


async def handle_list_users(*, limit: int = 100, offset: int = 0) -> UserListResponse:
    try:
        users = await list_users(limit=limit, offset=offset)
        total = await count_users()
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置",
        ) from e

    return UserListResponse(items=[to_user_response(u) for u in users], total=total)


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
    return to_user_response(user)


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
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except UserNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置",
        ) from e

    user_resp = to_user_response(updated.user)
    data = user_resp.model_dump()
    data["api_key"] = updated.api_key
    return UpdateUserResponse(**data)
