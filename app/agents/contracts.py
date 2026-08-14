from dataclasses import dataclass
from typing import Annotated, Callable, Literal

from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict


AgentName = str
WorkflowStatus = Literal["active", "completed", "cancelled"]
CURRENT_STATE_SCHEMA_VERSION = 5


class AgentCall(TypedDict):
    """A coordinator-owned request to execute one registered domain agent."""

    call_id: str
    agent: AgentName
    task: str
    context: dict


class AgentResult(TypedDict):
    """Stable result envelope projected by every domain agent."""

    agent: AgentName
    status: str
    summary: str
    data: dict
    warnings: list[dict]
    errors: list[dict]
    call_id: NotRequired[str]


class AgentCoordinationState(TypedDict, total=False):
    """State shared between the root coordinator and registered agents."""
    messages: Annotated[list, add_messages]
    route: AgentName
    workflow_agent: AgentName | None
    workflow_status: WorkflowStatus
    workflow_route_hints: list[str]
    active_agent: AgentName | None
    last_agent: AgentName | None
    handoff: dict | None
    handoff_count: int
    agent_status: str
    agent_result: AgentResult | None
    agent_results: list[AgentResult]
    pending_agent_call: AgentCall | None
    orchestration_phase: Literal[
        "idle", "using_tools", "delegating", "synthesizing", "done"
    ]
    orchestration_round: int
    next_action: str
    final_response: str | None
    execution_error: dict | None
    route_decision: dict
    state_schema_version: int


class RootState(AgentCoordinationState):
    """Domain-agnostic state owned by the coordinator."""


@dataclass(frozen=True)
class AgentSpec:
    name: AgentName
    description: str
    graph_factory: Callable
    router: Callable[[RootState], "RouteDecision"] | None = None
    priority: int = 0


@dataclass(frozen=True)
class RouteDecision:
    """Deterministic routing evidence returned by a specialized agent."""

    agent: AgentName
    matched: bool
    score: int
    reason: str
    kind: Literal["explicit", "continuation"] = "explicit"

    def __post_init__(self):
        if not 0 <= self.score <= 100:
            raise ValueError("RouteDecision.score 必须在 0 到 100 之间")

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "matched": self.matched,
            "score": self.score,
            "reason": self.reason,
            "kind": self.kind,
        }
