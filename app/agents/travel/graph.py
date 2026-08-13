from langgraph.graph import END, START, StateGraph

from app.agents.travel.nodes import (
    apply_revision_node,
    ask_missing_node,
    build_research_plan_node,
    cancel_travel_node,
    collect_trip_node,
    compose_plan_node,
    confirm_research_node,
    execute_research_node,
    extract_candidates_node,
    extract_revision_node,
    reject_research_node,
    recompose_revision_node,
    reset_travel_state_node,
    revision_feedback_node,
    route_after_confirmation,
    route_after_revision_apply,
    route_after_revision_extraction,
    route_after_validation,
    route_from_intent,
    route_intent_node,
    validate_trip_node,
    weather_node,
)
from app.agents.travel.state import TravelState


def travel_entry_node(state: TravelState) -> dict:
    result = route_intent_node(state)
    result.update({
        "route": "travel",
        "active_agent": "travel",
        "last_agent": "travel",
        "handoff": None,
        "agent_status": "running",
    })
    return result


def handoff_general_node(state: TravelState) -> dict:
    return {
        "handoff": {
            "target": "general",
            "reason": "本轮输入不属于当前旅行工作流",
            "preserve_travel_state": True,
        },
        "agent_status": "handoff",
    }


def _latest_ai_text(state: TravelState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, dict) and message.get("role") == "assistant":
            return str(message.get("content", ""))
        if getattr(message, "type", None) in {"ai", "assistant"}:
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else ""
    return ""


def travel_exit_node(state: TravelState) -> dict:
    """Project the private travel stage onto the root's generic workflow contract."""
    stage = state.get("travel_stage")
    if stage in {"collecting", "ready", "researching", "revising"}:
        status = "active"
    elif stage == "cancelled":
        status = "cancelled"
    else:
        status = "completed"
    warnings = list(state.get("warnings") or [])
    budget = dict(state.get("budget") or {})
    result_data = {
        "plan_id": state.get("plan_id"),
        "missing_fields": list(state.get("missing_fields") or []),
        "budget_summary": {
            key: budget.get(key)
            for key in (
                "currency", "total", "known_total", "completeness", "risk",
                "user_budget",
            )
            if key in budget
        },
    }
    route_hints = []
    for item in state.get("attraction_candidates", []):
        name = item.get("name")
        if name and name not in route_hints:
            route_hints.append(name)
    for day in state.get("itinerary", []):
        for activity in day.get("activities", []):
            name = activity.get("name")
            if name and name not in route_hints:
                route_hints.append(name)
    return {
        "workflow_agent": "travel",
        "workflow_status": status,
        "workflow_route_hints": route_hints[:50],
        "agent_status": status,
        "agent_result": {
            "agent": "travel",
            "status": status,
            "summary": _latest_ai_text(state),
            "data": result_data,
            "warnings": [item for item in warnings if item.get("severity") != "error"],
            "errors": [item for item in warnings if item.get("severity") == "error"],
        },
    }


def build_travel_graph(checkpointer=True):
    """Build the stateful travel workflow as an independent domain agent."""
    builder = StateGraph(TravelState)
    builder.add_node("route_intent", travel_entry_node)
    builder.add_node("handoff_general", handoff_general_node)
    builder.add_node("reset", reset_travel_state_node)
    builder.add_node("cancel", cancel_travel_node)
    builder.add_node("collect", collect_trip_node)
    builder.add_node("validate", validate_trip_node)
    builder.add_node("ask_missing", ask_missing_node)
    builder.add_node("build_research", build_research_plan_node)
    builder.add_node("confirm", confirm_research_node)
    builder.add_node("search", execute_research_node)
    builder.add_node("extract_candidates", extract_candidates_node)
    builder.add_node("reject_search", reject_research_node)
    builder.add_node("weather", weather_node)
    builder.add_node("compose", compose_plan_node)
    builder.add_node("extract_revision", extract_revision_node)
    builder.add_node("apply_revision", apply_revision_node)
    builder.add_node("revision_feedback", revision_feedback_node)
    builder.add_node("recompose_revision", recompose_revision_node)
    builder.add_node("exit", travel_exit_node)

    builder.add_edge(START, "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        route_from_intent,
        {
            "general": "handoff_general",
            "travel_new": "reset",
            "travel_continue": "collect",
            "travel_revision": "extract_revision",
            "travel_cancel": "cancel",
        },
    )
    builder.add_edge("handoff_general", "exit")
    builder.add_edge("reset", "collect")
    builder.add_edge("cancel", "exit")
    builder.add_edge("collect", "validate")
    builder.add_conditional_edges(
        "validate",
        route_after_validation,
        {"missing": "ask_missing", "ready": "build_research"},
    )
    builder.add_edge("ask_missing", "exit")
    builder.add_edge("build_research", "confirm")
    builder.add_conditional_edges(
        "confirm",
        route_after_confirmation,
        {"approved": "search", "rejected": "reject_search"},
    )
    builder.add_edge("search", "extract_candidates")
    builder.add_edge("extract_candidates", "weather")
    builder.add_edge("reject_search", "weather")
    builder.add_edge("weather", "compose")
    builder.add_edge("compose", "exit")
    builder.add_conditional_edges(
        "extract_revision",
        route_after_revision_extraction,
        {"valid": "apply_revision", "invalid": "revision_feedback"},
    )
    builder.add_conditional_edges(
        "apply_revision",
        route_after_revision_apply,
        {"applied": "recompose_revision", "invalid": "revision_feedback"},
    )
    builder.add_edge("revision_feedback", "exit")
    builder.add_edge("recompose_revision", "exit")
    builder.add_edge("exit", END)

    # True gives the child its own checkpoint namespace across parent invocations.
    return builder.compile(checkpointer=checkpointer, name="travel_agent")
