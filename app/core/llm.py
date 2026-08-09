from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.core.config import get_settings


@lru_cache
def get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.DEEPSEEK_MODEL,
        openai_api_key=s.DEEPSEEK_API_KEY,
        openai_api_base=s.DEEPSEEK_API_BASE,
        temperature=s.DEEPSEEK_TEMPERATURE,
    )
