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

    # ---- HTTP ----
    HTTP_TIMEOUT: int = int(os.getenv("HTTP_TIMEOUT", "15"))

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
    return s
