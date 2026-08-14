from app.agents.contracts import (
    CURRENT_STATE_SCHEMA_VERSION,
    AgentCall,
    RootState,
)
from app.agents.coordinator.general import run_general_handler
from app.agents.coordinator.messages import COORDINATOR_MESSAGE_NAME, latest_user_text
from app.agents.coordinator.publishing import publish_agent_results
from app.agents.coordinator.routing import choose_route
from app.agents.registry import AGENT_SPECS


MAX_ORCHESTRATION_ROUNDS = 3


def _agent_call(agent: str, state: RootState, *, reason: str) -> AgentCall:
    messages = state.get("messages", [])
    latest = messages[-1] if messages else None
    message_id = getattr(latest, "id", None)
    round_number = state.get("orchestration_round", 0) + 1
    return {
        "call_id": str(message_id or f"{agent}:{round_number}"),
        "agent": agent,
        "task": latest_user_text(state),
        "context": {
            "reason": reason,
            "workflow_agent": state.get("workflow_agent"),
            "workflow_status": state.get("workflow_status"),
        },
    }


def coordinator_node(state: RootState) -> dict:
    """Coordinate one turn: answer directly, delegate, then publish the result."""
    phase = state.get("orchestration_phase", "idle")

    if phase == "using_tools":
        return run_general_handler(state)

    if phase == "delegating":
        return {"next_action": "execute_agent"}

    if phase == "synthesizing":
        handoff = state.get("handoff") or {}
        target = handoff.get("target")
        if target == "general":
            return run_general_handler(
                state,
                handoff=None,
                handoff_count=state.get("handoff_count", 0) + 1,
            )
        if (
            target in AGENT_SPECS
            and state.get("orchestration_round", 0) < MAX_ORCHESTRATION_ROUNDS
        ):
            call = _agent_call(target, state, reason=str(handoff.get("reason", "handoff")))
            return {
                "route": target,
                "handoff": None,
                "handoff_count": state.get("handoff_count", 0) + 1,
                "pending_agent_call": call,
                "orchestration_phase": "delegating",
                "orchestration_round": state.get("orchestration_round", 0) + 1,
                "next_action": "execute_agent",
            }
        return publish_agent_results(state)

    route, route_decision = choose_route(state)
    if route == "general":
        return run_general_handler(
            state,
            route_decision=route_decision,
            handoff=None,
            handoff_count=0,
        )

    call = _agent_call(route, state, reason=route_decision.get("reason", ""))
    return {
        "route": route,
        "route_decision": route_decision,
        "handoff": None,
        "handoff_count": 0,
        "active_agent": COORDINATOR_MESSAGE_NAME,
        "agent_status": "delegating",
        "agent_results": [],
        "pending_agent_call": call,
        "orchestration_phase": "delegating",
        "orchestration_round": 1,
        "next_action": "execute_agent",
        "final_response": None,
        "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
    }


def route_from_coordinator(state: RootState) -> str:
    return state.get("next_action", "done")
