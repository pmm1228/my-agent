from typing import Literal


ToolDomain = Literal["weather", "search", "file", "general"]


DOMAIN_DESCRIPTIONS: dict[ToolDomain, str] = {
    "weather": "天气、预报、台风、气象灾害等实时气象查询",
    "search": "联网搜索、新闻、开放网页信息查询",
    "file": "本地文件、文档、表格、资料处理",
    "general": "不需要专门工具的一般对话",
}


def list_domains() -> dict[ToolDomain, str]:
    """Return the domains a future supervisor/router can choose from."""
    return DOMAIN_DESCRIPTIONS.copy()
