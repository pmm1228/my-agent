from fastapi import APIRouter

from app.api.handlers.auth import handle_login
from app.api.schemas.auth import LoginRequest, LoginResponse


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    summary="用户名密码登录",
    description="校验用户名和密码，返回后续接口使用的 Bearer Token。",
    response_model=LoginResponse,
)
async def login(req: LoginRequest) -> LoginResponse:
    return await handle_login(req)
