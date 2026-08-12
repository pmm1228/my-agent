from app.tools.search.tavily import search_web
from app.tools.search.webpage import fetch_webpage

search_tools = [search_web, fetch_webpage]

__all__ = ["search_tools", "search_web", "fetch_webpage"]
