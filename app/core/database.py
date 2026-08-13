import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.security import generate_api_key, hash_api_key, hash_password
from app.utils.logging import get_logger


logger = get_logger(__name__)

_pool = None
_pool_lock = asyncio.Lock()


class DatabaseNotConfigured(RuntimeError):
    pass


_CONVERSATION_TABLES = ("chat_messages", "chat_sessions")


def get_database_url() -> str:
    settings = get_settings()
    return settings.DATABASE_URL or settings.POSTGRES_URL


async def get_pool():
    global _pool

    if _pool is not None:
        return _pool

    database_url = get_database_url()
    if not database_url:
        raise DatabaseNotConfigured("DATABASE_URL 或 POSTGRES_URL 未配置")

    async with _pool_lock:
        if _pool is not None:
            return _pool

        try:
            from psycopg_pool import AsyncConnectionPool
            from psycopg.rows import dict_row
        except ImportError as e:
            raise RuntimeError(
                "数据库功能需要安装 psycopg_pool 和 psycopg[binary]"
            ) from e

        pool = AsyncConnectionPool(
            database_url,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        try:
            await pool.open()
        except Exception:
            try:
                await pool.close()
            except Exception:
                pass
            raise
        _pool = pool
        return _pool


@asynccontextmanager
async def db_connection() -> AsyncIterator:
    pool = await get_pool()
    async with pool.connection() as conn:
        yield conn


async def init_database() -> bool:
    try:
        pool = await get_pool()
    except DatabaseNotConfigured:
        logger.warning("DATABASE_URL/POSTGRES_URL 未配置，跳过用户表初始化")
        return False

    async with pool.connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_users (
                id uuid PRIMARY KEY,
                username text NOT NULL UNIQUE,
                display_name text,
                api_key_hash text NOT NULL UNIQUE,
                password_hash text,
                role text NOT NULL DEFAULT 'user',
                is_active boolean NOT NULL DEFAULT true,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT app_users_role_check CHECK (role IN ('admin', 'user'))
            )
            """
        )
        await conn.execute(
            """
            ALTER TABLE app_users
            ADD COLUMN IF NOT EXISTS password_hash text
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS app_users_role_idx
            ON app_users (role)
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id uuid PRIMARY KEY,
                user_id uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                thread_id text NOT NULL,
                title text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (user_id, thread_id)
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS chat_sessions_user_updated_idx
            ON chat_sessions (user_id, updated_at DESC)
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id bigserial PRIMARY KEY,
                session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role text NOT NULL,
                content text NOT NULL,
                tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT chat_messages_role_check
                    CHECK (role IN ('user', 'assistant', 'system', 'tool'))
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS chat_messages_session_created_idx
            ON chat_messages (session_id, created_at ASC, id ASC)
            """
        )
        await _bootstrap_admin(conn)

    logger.info("数据库初始化完成：用户表和聊天历史表已就绪")
    return True


async def _table_exists(conn, table_name: str) -> bool:
    cur = await conn.execute(
        "SELECT to_regclass(%s) AS table_name",
        (f"public.{table_name}",),
    )
    row = await cur.fetchone()
    return bool(row and row["table_name"] is not None)


async def reset_chat_history_data() -> dict[str, int]:
    """Clear business chat history through DATABASE_URL while preserving users."""
    pool = await get_pool()
    cleared: dict[str, int] = {}
    async with pool.connection() as conn:
        async with conn.transaction():
            existing = []
            for table_name in _CONVERSATION_TABLES:
                if not await _table_exists(conn, table_name):
                    continue
                existing.append(table_name)
                cur = await conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
                cleared[table_name] = (await cur.fetchone())["count"]

            conversation_tables = [
                name for name in _CONVERSATION_TABLES if name in existing
            ]
            if conversation_tables:
                await conn.execute(
                    f"TRUNCATE TABLE {', '.join(conversation_tables)} RESTART IDENTITY"
                )

    logger.info("业务聊天历史已清空，用户与长期记忆数据保持不变")
    return cleared


async def close_database() -> None:
    global _pool

    async with _pool_lock:
        pool = _pool
        _pool = None
        if pool is not None:
            await pool.close()


async def _bootstrap_admin(conn) -> None:
    settings = get_settings()
    username = settings.ADMIN_USERNAME.strip() or "admin"
    api_key = settings.ADMIN_API_KEY.strip()
    admin_password = settings.ADMIN_PASSWORD.strip()

    has_api_key = bool(api_key)
    has_password = bool(admin_password)

    if not has_api_key and not has_password:
        cur = await conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM app_users
            WHERE role = 'admin' AND is_active = true
            """
        )
        admin_count = (await cur.fetchone())["count"]
        if admin_count:
            logger.info("ADMIN_API_KEY/ADMIN_PASSWORD 均未配置，保留已有管理员账号")
            return
        raise RuntimeError(
            "ADMIN_API_KEY 和 ADMIN_PASSWORD 均未配置，且数据库中没有管理员。"
            "请先在 .env 中设置至少一个。"
        )

    if not api_key:
        api_key = generate_api_key()
        has_api_key = True
        logger.warning(
            "ADMIN_API_KEY 未配置，自动生成临时 API Key（请尽快配置 ADMIN_API_KEY）"
        )

    password_hash = hash_password(admin_password) if has_password else None

    await conn.execute(
        """
        INSERT INTO app_users (
            id, username, display_name,
            api_key_hash, password_hash,
            role, is_active
        )
        VALUES (%s, %s, %s, %s, %s, 'admin', true)
        ON CONFLICT (username) DO UPDATE SET
            api_key_hash = CASE
                WHEN %s THEN EXCLUDED.api_key_hash
                ELSE app_users.api_key_hash
            END,
            password_hash = CASE
                WHEN %s THEN EXCLUDED.password_hash
                ELSE app_users.password_hash
            END,
            role = 'admin',
            is_active = true,
            updated_at = now()
        """,
        (
            uuid.uuid4(),
            username,
            "Bootstrap Admin",
            hash_api_key(api_key),
            password_hash,
            has_api_key,
            has_password,
        ),
    )
