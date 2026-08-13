from fastapi import APIRouter

from app.api.handlers.system import handle_health
from app.api.schemas.system import HealthResponse


router = APIRouter(tags=["system"])


@router.get(
    "/health",
    summary="健康检查",
    description="返回服务状态和当前模型名称。部署时可作为 liveness probe。",
    response_model=HealthResponse,
)
async def health() -> dict:
    return await handle_health()
