from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.core.checkpointer import get_checkpointer
from app.graph.nodes import chatbot
from app.graph.state import State
from app.tools.registry import all_tools


def build_graph(checkpointer=None):
    """构建 LangGraph：单 Agent + ToolNode + 条件边。

    演进说明（预留位）：
    当前保持单 Agent；工具分组在 app.tools.registry 中维护。
    当工具数量 > 15 或业务域差异明显时，可在此引入 Supervisor 模式：
      supervisor → (weather_agent | typhoon_agent | search_agent | ...) → END
    app.graph.router 已预留领域说明，入口不变，只是内部边的路由方式变化。
    """
    if checkpointer is None:
        checkpointer = get_checkpointer()

    builder = StateGraph(State)
    builder.add_node("chatbot", chatbot)
    builder.add_node("tools", ToolNode(all_tools))
    builder.add_edge(START, "chatbot")
    builder.add_conditional_edges("chatbot", tools_condition)
    builder.add_edge("tools", "chatbot")

    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
