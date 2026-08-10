from uuid import UUID

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.database import DatabaseNotConfigured
from app.core.security import ExpiredToken, InvalidToken, decode_access_token
from app.services.user_service import UserRecord, get_user_by_api_key, get_user_by_id


bearer_header = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _auth_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _ensure_active_user(user: UserRecord | None) -> UserRecord:
    if user is None:
        raise _auth_error("无效的登录凭证")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用",
        )
    return user


async def _get_user_from_token(token: str) -> UserRecord | None:
    settings = get_settings()
    try:
        payload = decode_access_token(token, secret=settings.JWT_SECRET)
        user_id = UUID(str(payload.get("sub")))
    except ExpiredToken as e:
        raise _auth_error("登录已过期，请重新登录") from e
    except (InvalidToken, ValueError, TypeError) as e:
        raise _auth_error("无效的登录凭证") from e

    try:
        return await get_user_by_id(user_id)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法校验权限",
        ) from e


async def _get_user_from_api_key(api_key: str) -> UserRecord | None:
    try:
        return await get_user_by_api_key(api_key)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法校验权限",
        ) from e


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_header),
    api_key: str | None = Security(api_key_header),
) -> UserRecord:
    """强制鉴权：优先使用 Authorization Bearer Token，兼容 X-API-Key。"""
    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise _auth_error("Authorization 必须使用 Bearer Token")
        return _ensure_active_user(await _get_user_from_token(credentials.credentials))

    if api_key:
        return _ensure_active_user(await _get_user_from_api_key(api_key))

    raise _auth_error("缺少 Authorization Bearer Token")


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
