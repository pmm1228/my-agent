import json

from langchain_core.tools import tool

from app.core.config import get_settings
from app.utils.http import http_client


def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Execute one Tavily query and return JSON-compatible results.

    Raises configuration and request errors so workflow callers can distinguish a
    partial research failure from an empty result. The public LangChain tool below
    retains the existing user-facing string behavior.
    """
    query = query.strip()
    if not query:
        raise ValueError("搜索关键词不能为空。")

    settings = get_settings()
    if not settings.TAVILY_API_KEY:
        raise RuntimeError("联网搜索未配置：缺少 TAVILY_API_KEY。")

    limit = min(max(1, max_results), settings.WEB_SEARCH_MAX_RESULTS, 10)
    try:
        with http_client() as client:
            response = client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {settings.TAVILY_API_KEY}"},
                json={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": limit,
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"联网搜索失败：{exc}") from exc

    results = []
    for item in payload.get("results", [])[:limit]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "published_at": item.get("published_date"),
            }
        )
    return results


@tool
def search_web(query: str, max_results: int = 5) -> str:
    """搜索公开互联网。仅用于实时、近期变化、需要外部查证或用户明确要求搜索的信息。"""
    try:
        results = tavily_search(query, max_results)
    except Exception as exc:
        return str(exc)
    if not results:
        return "没有找到相关搜索结果。"
    return json.dumps(results, ensure_ascii=False)
