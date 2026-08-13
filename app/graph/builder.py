from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableLambda

from app.agents.contracts import RootState
from app.agents.executor import (
    AGENT_EXECUTOR_ERROR_KEY,
    agent_executor_node,
    agent_failure_fallback,
    collect_agent_result_node,
    route_from_agent_executor,
)
from app.agents.registry import build_registered_agents
from app.agents.supervisor import (
    main_agent_node,
    route_from_main_agent,
)
from app.core.checkpointer import get_checkpointer
from app.graph.web_confirmation import tools_with_web_confirmation


def build_graph(checkpointer=None):
    """Compose main-agent → domain-agent → main-agent orchestration."""
    if checkpointer is None:
        checkpointer = get_checkpointer()

    agents = build_registered_agents(include_general=False)
    builder = StateGraph(RootState)
    builder.add_node("main_agent", main_agent_node)
    builder.add_node("agent_executor", agent_executor_node)
    builder.add_node("collect_agent_result", collect_agent_result_node)
    builder.add_node("tools", tools_with_web_confirmation)
    for name, agent_graph in agents.items():
        safe_agent_graph = agent_graph.with_fallbacks(
            [RunnableLambda(agent_failure_fallback)],
            exception_key=AGENT_EXECUTOR_ERROR_KEY,
        )
        builder.add_node(f"{name}_agent", safe_agent_graph)

    builder.add_edge(START, "main_agent")
    builder.add_conditional_edges(
        "main_agent",
        route_from_main_agent,
        {
            "execute_agent": "agent_executor",
            "tools": "tools",
            "done": END,
        },
    )
    builder.add_conditional_edges(
        "agent_executor",
        route_from_agent_executor,
        {
            **{name: f"{name}_agent" for name in agents},
            "invalid": "collect_agent_result",
        },
    )
    builder.add_edge("tools", "main_agent")
    for name in agents:
        builder.add_edge(f"{name}_agent", "collect_agent_result")
    builder.add_edge("collect_agent_result", "main_agent")
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
