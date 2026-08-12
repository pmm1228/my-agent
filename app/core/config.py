import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ---- LLM ----
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_API_BASE: str = os.getenv(
        "DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"
    )
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_TEMPERATURE: float = float(
        os.getenv("DEEPSEEK_TEMPERATURE", "0.2")
    )

    # ---- Checkpointer ----
    CHECKPOINTER_TYPE: Literal["memory", "postgres"] = os.getenv(
        "CHECKPOINTER_TYPE", "memory"
    )
    POSTGRES_URL: str = os.getenv("POSTGRES_URL", "")
    CONVERSATION_LOCK_TIMEOUT_SECONDS: float = float(
        os.getenv("CONVERSATION_LOCK_TIMEOUT_SECONDS", "30")
    )

    # ---- Database / Auth ----
    DATABASE_URL: str = os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", ""))
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    JWT_SECRET: str = os.getenv(
        "JWT_SECRET",
        os.getenv("ADMIN_API_KEY", "my-agent-local-jwt-secret"),
    )
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    # ---- HTTP ----
    HTTP_TIMEOUT: int = int(os.getenv("HTTP_TIMEOUT", "15"))

    # ---- Web search ----
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    WEB_SEARCH_MAX_RESULTS: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
    WEB_PAGE_MAX_BYTES: int = int(os.getenv("WEB_PAGE_MAX_BYTES", "1000000"))

    # ---- API ----
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未配置，请在 .env 中设置"
        )
    if s.CONVERSATION_LOCK_TIMEOUT_SECONDS <= 0:
        raise RuntimeError("CONVERSATION_LOCK_TIMEOUT_SECONDS 必须大于 0")
    if not 1 <= s.WEB_SEARCH_MAX_RESULTS <= 10:
        raise RuntimeError("WEB_SEARCH_MAX_RESULTS 必须在 1 到 10 之间")
    if s.WEB_PAGE_MAX_BYTES <= 0:
        raise RuntimeError("WEB_PAGE_MAX_BYTES 必须大于 0")
    return s
