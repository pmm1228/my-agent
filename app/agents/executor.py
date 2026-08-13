from langgraph.errors import GraphBubbleUp

from app.agents.contracts import AgentResult, RootState
from app.agents.registry import AGENT_SPECS


AGENT_EXECUTOR_ERROR_KEY = "_agent_executor_error"


def _failed_result(agent: str, *, code: str, message: str) -> AgentResult:
    return {
        "agent": agent,
        "status": "failed",
        "summary": message,
        "data": {},
        "warnings": [],
        "errors": [{"code": code, "message": message}],
    }


def agent_executor_node(state: RootState) -> dict:
    """Validate an AgentCall and select its registered domain subgraph."""
    call = state.get("pending_agent_call")
    if not call:
        return {
            "agent_result": _failed_result(
                "unknown",
                code="MISSING_AGENT_CALL",
                message="主 Agent 没有提供可执行的子 Agent 调用。",
            ),
            "next_action": "invalid",
            "agent_status": "failed",
        }

    agent = call.get("agent", "unknown")
    if agent == "general" or agent not in AGENT_SPECS:
        return {
            "agent_result": _failed_result(
                agent,
                code="UNKNOWN_AGENT",
                message=f"未注册可执行的子 Agent：{agent}",
            ),
            "next_action": "invalid",
            "agent_status": "failed",
        }

    return {
        "route": agent,
        "active_agent": agent,
        "agent_status": "running",
        "next_action": agent,
    }


def route_from_agent_executor(state: RootState) -> str:
    return state.get("next_action", "invalid")


def agent_failure_fallback(state: dict) -> dict:
    """Convert domain failures to AgentResult while preserving graph interrupts."""
    error = state.get(AGENT_EXECUTOR_ERROR_KEY)
    if isinstance(error, GraphBubbleUp):
        raise error

    call = state.get("pending_agent_call") or {}
    agent = str(call.get("agent") or state.get("route") or "unknown")
    error_type = type(error).__name__ if error is not None else "UnknownError"
    return {
        "agent_result": _failed_result(
            agent,
            code="AGENT_EXECUTION_FAILED",
            message=f"{agent} Agent 执行失败，主 Agent 已接管本轮请求。",
        ),
        "agent_status": "failed",
        "handoff": None,
        "execution_error": {
            "type": error_type,
            "message": str(error) if error is not None else "未知错误",
        },
    }


def collect_agent_result_node(state: RootState) -> dict:
    """Normalize a child result before returning control to the main agent."""
    call = state.get("pending_agent_call") or {}
    agent = str(call.get("agent") or state.get("route") or "unknown")
    raw_result = state.get("agent_result")
    if raw_result is None:
        result = _failed_result(
            agent,
            code="EMPTY_AGENT_RESULT",
            message=f"{agent} Agent 没有返回可用结果。",
        )
    else:
        result = dict(raw_result)
        result.setdefault("agent", agent)
        result.setdefault("status", "completed")
        result.setdefault("summary", "")
        result.setdefault("data", {})
        result.setdefault("warnings", [])
        result.setdefault("errors", [])

    call_id = call.get("call_id")
    if call_id:
        result["call_id"] = str(call_id)

    return {
        "active_agent": "main",
        "last_agent": agent,
        "agent_status": result.get("status", "completed"),
        "agent_result": result,
        "agent_results": [*(state.get("agent_results") or []), result],
        "orchestration_phase": "synthesizing",
        "next_action": "main_agent",
    }
