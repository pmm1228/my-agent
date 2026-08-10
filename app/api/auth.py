from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.database import DatabaseNotConfigured
from app.services.user_service import UserRecord, get_user_by_api_key


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_user(
    api_key: str | None = Security(api_key_header),
) -> UserRecord:
    """强制鉴权：必须提供有效的 X-API-Key，且用户处于激活状态。"""
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 X-API-Key",
        )

    try:
        user = await get_user_by_api_key(api_key)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法校验权限",
        ) from e

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用",
        )

    return user


async def require_admin_user(
    user: UserRecord = Security(require_user),
) -> UserRecord:
    """在 require_user 基础上额外要求 admin 角色。"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user
