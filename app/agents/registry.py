from app.agents.contracts import AgentSpec
from app.agents.general.graph import build_general_graph
from app.agents.travel.graph import build_travel_graph
from app.agents.travel.routing import route_travel_request


AGENT_SPECS = {
    "general": AgentSpec(
        name="general",
        description="普通问答以及通用工具调用",
        graph_factory=build_general_graph,
        priority=0,
    ),
    "travel": AgentSpec(
        name="travel",
        description="多轮旅行规划、联网研究、天气、预算和行程修改",
        graph_factory=build_travel_graph,
        router=route_travel_request,
        priority=100,
    ),
}


def build_registered_agents(*, include_general: bool = True) -> dict:
    return {
        name: spec.graph_factory()
        for name, spec in AGENT_SPECS.items()
        if include_general or name != "general"
    }
