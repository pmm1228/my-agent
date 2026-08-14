from langchain_core.messages import AIMessage

from app.agents.contracts import CURRENT_STATE_SCHEMA_VERSION, AgentResult, RootState
from app.agents.coordinator.messages import (
    COORDINATOR_MESSAGE_NAME,
    GENERAL_HANDLER_NAME,
    message_text,
)
from app.graph.nodes import chatbot


def run_general_handler(state: RootState, **extra) -> dict:
    """Let the coordinator answer directly or use ordinary data tools."""
    update = chatbot(state)
    response = update["messages"][-1]
    tool_calls = getattr(response, "tool_calls", [])
    if tool_calls:
        return {
            **update,
            **extra,
            "route": GENERAL_HANDLER_NAME,
            "active_agent": COORDINATOR_MESSAGE_NAME,
            "last_agent": GENERAL_HANDLER_NAME,
            "agent_status": "using_tools",
            "orchestration_phase": "using_tools",
            "next_action": "tools",
            "pending_agent_call": None,
            "final_response": None,
            "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
        }

    summary = message_text(response)
    if isinstance(response, AIMessage):
        response = response.model_copy(update={"name": COORDINATOR_MESSAGE_NAME})
        update = {"messages": [response]}
    result: AgentResult = {
        "agent": GENERAL_HANDLER_NAME,
        "status": "completed",
        "summary": summary,
        "data": {},
        "warnings": [],
        "errors": [],
    }
    return {
        **update,
        **extra,
        "route": GENERAL_HANDLER_NAME,
        "active_agent": COORDINATOR_MESSAGE_NAME,
        "last_agent": GENERAL_HANDLER_NAME,
        "agent_status": "completed",
        "agent_result": result,
        "agent_results": [result],
        "orchestration_phase": "done",
        "orchestration_round": 0,
        "next_action": "done",
        "pending_agent_call": None,
        "final_response": summary,
        "state_schema_version": CURRENT_STATE_SCHEMA_VERSION,
    }
