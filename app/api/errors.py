from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.chat_service import AgentConflictError


async def agent_conflict_exception_handler(
    _request: Request,
    exc: AgentConflictError,
) -> JSONResponse:
    return JSONResponse(status_code=409, content=exc.as_dict())
