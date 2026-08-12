from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from app.graph.state import State
from app.tools.registry import all_tools


CONFIRMATION_REQUIRED_TOOLS = {"search_web"}
tool_node = ToolNode(all_tools)


async def tools_with_web_confirmation(state: State, config: RunnableConfig) -> dict:
    """Require one user decision before executing a batch containing web tools."""
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", [])
    web_calls = [
        call
        for call in tool_calls
        if call.get("name") in CONFIRMATION_REQUIRED_TOOLS
    ]

    if web_calls:
        approved = interrupt(
            {
                "type": "web_confirmation",
                "message": "本次回答需要调用 Tavily 联网搜索，并消耗 Tavily 搜索额度，是否允许？",
                "tool_calls": [
                    {"name": call["name"], "args": call.get("args", {})}
                    for call in web_calls
                ],
            }
        )
        if approved is not True:
            return {
                "messages": [
                    ToolMessage(
                        content="用户拒绝了本次联网请求。请在不联网的前提下回答，并说明无法核实实时信息。",
                        tool_call_id=call["id"],
                    )
                    for call in tool_calls
                ]
            }

    return await tool_node.ainvoke(state, config)
