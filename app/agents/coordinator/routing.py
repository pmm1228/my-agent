from app.agents.contracts import (
    CURRENT_STATE_SCHEMA_VERSION,
    RootState,
    RouteDecision,
)
from app.agents.registry import AGENT_SPECS


ROUTE_SCORE_THRESHOLD = 60


def choose_route(state: RootState) -> tuple[str, dict]:
    """Choose between the general handler and registered domain agents."""
    candidates: list[tuple[RouteDecision, int]] = []
    evaluations: list[dict] = []
    for name, spec in AGENT_SPECS.items():
        if spec.router is None:
            continue
        try:
            decision = spec.router(state)
        except Exception as exc:
            evaluations.append({
                "agent": name,
                "matched": False,
                "score": 0,
                "reason": "领域路由器执行失败",
                "error_type": type(exc).__name__,
            })
            continue
        evaluation = decision.as_dict()
        evaluation["priority"] = spec.priority
        evaluations.append(evaluation)
        if decision.matched and decision.agent == name:
            candidates.append((decision, spec.priority))

    eligible = [item for item in candidates if item[0].score >= ROUTE_SCORE_THRESHOLD]
    if not eligible:
        return "general", {
            "agent": "general",
            "score": 0,
            "reason": "没有达到阈值的领域 Agent",
            "candidates": evaluations,
        }

    explicit = [item for item in eligible if item[0].kind == "explicit"]
    selection_pool = explicit or eligible
    selection_pool.sort(key=lambda item: (item[0].score, item[1]), reverse=True)
    best, best_priority = selection_pool[0]
    tied = [
        item for item in selection_pool[1:]
        if item[0].score == best.score and item[1] == best_priority
    ]
    if tied:
        return "general", {
            "agent": "general",
            "score": best.score,
            "reason": "多个领域 Agent 得分和优先级相同，回退通用处理",
            "ambiguous": True,
            "candidates": evaluations,
        }

    result = best.as_dict()
    result["priority"] = best_priority
    return best.agent, result


def route_request_node(state: RootState) -> dict:
    """Expose routing as a standalone coordinator step for focused tests."""
    route, route_decision = choose_route(state)
    return {
        "route": route,
        "route_decision": route_decision,
        "handoff": None,
        "handoff_count": 0,
        "agent_status": "routing",
        "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
    }
