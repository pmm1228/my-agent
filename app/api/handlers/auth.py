from fastapi import HTTPException, status

from app.api.mappers import to_user_response
from app.api.schemas.auth import LoginRequest, LoginResponse
from app.core.config import get_settings
from app.core.database import DatabaseNotConfigured
from app.core.security import create_access_token
from app.services.user_service import authenticate_user


async def handle_login(req: LoginRequest) -> LoginResponse:
    try:
        user = await authenticate_user(req.username.strip(), req.password)
    except DatabaseNotConfigured as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库未配置，无法登录",
        ) from e
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已禁用",
        )

    settings = get_settings()
    expires_in = max(settings.JWT_EXPIRE_MINUTES, 1) * 60
    access_token = create_access_token(
        subject=str(user.id),
        secret=settings.JWT_SECRET,
        expires_in_seconds=expires_in,
        extra={"username": user.username, "role": user.role},
    )

    return LoginResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=to_user_response(user),
    )
