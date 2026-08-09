from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import get_settings


def get_checkpointer() -> BaseCheckpointSaver:
    s = get_settings()

    if s.CHECKPOINTER_TYPE == "postgres":
        try:
            from langgraph_checkpoint_postgres import PostgresSaver
        except ImportError as e:
            raise RuntimeError(
                "CHECKPOINTER_TYPE=postgres 但未安装 langgraph-checkpoint-postgres。"
                "请 pip install langgraph-checkpoint-postgres asyncpg"
            ) from e
        if not s.POSTGRES_URL:
            raise RuntimeError("CHECKPOINTER_TYPE=postgres 需要设置 POSTGRES_URL")
        return PostgresSaver.from_conn_string(s.POSTGRES_URL)

    return MemorySaver()
