from app.tools.weather.registry import weather_tools
from app.tools.search.registry import search_tools

# 工具按领域分组，便于后续接入 router/supervisor。
file_tools = []

tool_groups = {
    "weather": weather_tools,
    "search": search_tools,
    "file": file_tools,
}

all_tools = [tool for tools in tool_groups.values() for tool in tools]


__all__ = ["all_tools", "tool_groups", "weather_tools", "search_tools", "file_tools"]
