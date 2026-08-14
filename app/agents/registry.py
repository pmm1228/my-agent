from app.agents.contracts import AgentSpec
from app.agents.travel.graph import build_travel_graph
from app.agents.travel.routing import route_travel_request


DOMAIN_AGENT_SPECS = {
    "travel": AgentSpec(
        name="travel",
        description="多轮旅行规划、联网研究、天气、预算和行程修改",
        graph_factory=build_travel_graph,
        router=route_travel_request,
        priority=100,
    ),
}

AGENT_SPECS = DOMAIN_AGENT_SPECS


def build_registered_agents() -> dict:
    return {
        name: spec.graph_factory()
        for name, spec in AGENT_SPECS.items()
    }
