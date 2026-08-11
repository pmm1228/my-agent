import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.database import DatabaseNotConfigured, db_connection
from app.core.security import generate_api_key, hash_api_key, hash_password, verify_password


UserRole = Literal["admin", "user"]
_USER_ADMIN_GUARD_LOCK_ID = 722790106067390913


@dataclass(slots=True)
class UserRecord:
    id: uuid.UUID
    username: str
    display_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class CreatedUser:
    user: UserRecord
    api_key: str


class UserAlreadyExists(ValueError):
    pass


class UserNotFound(ValueError):
    pass


class CannotDeleteLastAdmin(ValueError):
    pass


def _row_to_user(row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _is_unique_violation(exc: Exception) -> bool:
    return getattr(exc, "sqlstate", None) == "23505"


async def _table_exists(conn, table_name: str) -> bool:
    cur = await conn.execute(
        "SELECT to_regclass(%s) AS table_name",
        (f"public.{table_name}",),
    )
    row = await cur.fetchone()
    return row["table_name"] is not None


async def _delete_user_checkpoints(conn, user_id: uuid.UUID) -> None:
    checkpoint_prefix = f"user:{user_id}:thread:%"
    for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
        if not await _table_exists(conn, table_name):
            continue
        await conn.execute(
            f"DELETE FROM {table_name} WHERE thread_id LIKE %s",
            (checkpoint_prefix,),
        )


async def _lock_user_admin_guard(conn) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(%s)",
        (_USER_ADMIN_GUARD_LOCK_ID,),
    )


async def create_user(
    *,
    username: str,
    password: str | None = None,
    role: UserRole = "user",
    display_name: str | None = None,
    api_key: str | None = None,
    is_active: bool = True,
) -> CreatedUser:
    raw_api_key = api_key or generate_api_key()
    pwd_hash = hash_password(password) if password else None

    try:
        async with db_connection() as conn:
            try:
                cur = await conn.execute(
                    """
                    INSERT INTO app_users (
                        id,
                        username,
                        display_name,
                        api_key_hash,
                        password_hash,
                        role,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING
                        id,
                        username,
                        display_name,
                        role,
                        is_active,
                        created_at,
                        updated_at
                    """,
                    (
                        uuid.uuid4(),
                        username,
                        display_name,
                        hash_api_key(raw_api_key),
                        pwd_hash,
                        role,
                        is_active,
                    ),
                )
            except Exception as e:
                if _is_unique_violation(e):
                    raise UserAlreadyExists("用户名或 API Key 已存在") from e
                raise

            row = await cur.fetchone()
    except DatabaseNotConfigured:
        raise

    return CreatedUser(user=_row_to_user(row), api_key=raw_api_key)


async def authenticate_user(username: str, password: str) -> UserRecord | None:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role,
                is_active,
                created_at,
                updated_at,
                password_hash
            FROM app_users
            WHERE username = %s
            LIMIT 1
            """,
            (username,),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    if not verify_password(password, row["password_hash"]):
        return None

    return _row_to_user(row)


async def delete_user(user_id: uuid.UUID) -> UserRecord:
    async with db_connection() as conn:
        async with conn.transaction():
            await _lock_user_admin_guard(conn)
            cur = await conn.execute(
                """
                SELECT
                    id,
                    username,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    updated_at
                FROM app_users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )
            existing = await cur.fetchone()

            if existing is None:
                raise UserNotFound("用户不存在")

            if existing["role"] == "admin" and existing["is_active"]:
                admin_cur = await conn.execute(
                    """
                    SELECT id
                    FROM app_users
                    WHERE role = 'admin' AND is_active = true
                    ORDER BY id
                    FOR UPDATE
                    """
                )
                active_admin_count = len(await admin_cur.fetchall())
                if active_admin_count <= 1:
                    raise CannotDeleteLastAdmin("不能删除最后一个活跃管理员")

            await _delete_user_checkpoints(conn, user_id)
            cur = await conn.execute(
                """
                DELETE FROM app_users
                WHERE id = %s
                RETURNING
                    id,
                    username,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    updated_at
                """,
                (user_id,),
            )
            row = await cur.fetchone()

    return _row_to_user(row)


async def get_user_by_api_key(api_key: str) -> UserRecord | None:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role,
                is_active,
                created_at,
                updated_at
            FROM app_users
            WHERE api_key_hash = %s
            LIMIT 1
            """,
            (hash_api_key(api_key),),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    return _row_to_user(row)


async def get_user_by_id(user_id: uuid.UUID) -> UserRecord | None:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role,
                is_active,
                created_at,
                updated_at
            FROM app_users
            WHERE id = %s
            """,
            (user_id,),
        )
        row = await cur.fetchone()

    if row is None:
        return None

    return _row_to_user(row)


async def list_users(
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[UserRecord]:
    async with db_connection() as conn:
        cur = await conn.execute(
            """
            SELECT
                id,
                username,
                display_name,
                role,
                is_active,
                created_at,
                updated_at
            FROM app_users
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = await cur.fetchall()

    return [_row_to_user(r) for r in rows]


async def count_users() -> int:
    async with db_connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) AS count FROM app_users")
        row = await cur.fetchone()

    return row["count"]


@dataclass(slots=True)
class UpdatedUser:
    user: UserRecord
    api_key: str | None = None


async def update_user(
    user_id: uuid.UUID,
    *,
    role: UserRole | None = None,
    is_active: bool | None = None,
    display_name: str | None = None,
    update_display_name: bool = False,
    password: str | None = None,
    reset_api_key: bool = False,
) -> UpdatedUser:
    async with db_connection() as conn:
        async with conn.transaction():
            if role is not None or is_active is not None:
                await _lock_user_admin_guard(conn)
            cur = await conn.execute(
                """
                SELECT
                    id,
                    username,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    updated_at
                FROM app_users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )
            current_row = await cur.fetchone()
            if current_row is None:
                raise UserNotFound("用户不存在")

            current = _row_to_user(current_row)
            target_role = role if role is not None else current.role
            target_active = is_active if is_active is not None else current.is_active

            removes_active_admin = (
                current.role == "admin"
                and current.is_active
                and (target_role != "admin" or not target_active)
            )
            if removes_active_admin:
                cur = await conn.execute(
                    """
                    SELECT id
                    FROM app_users
                    WHERE role = 'admin' AND is_active = true
                    ORDER BY id
                    FOR UPDATE
                    """
                )
                active_admin_count = len(await cur.fetchall())
                if active_admin_count <= 1:
                    raise CannotDeleteLastAdmin("不能禁用最后一个活跃管理员")

            updates: list[str] = []
            params: list = []

            if role is not None:
                updates.append("role = %s")
                params.append(role)
            if is_active is not None:
                updates.append("is_active = %s")
                params.append(is_active)
            if update_display_name:
                updates.append("display_name = %s")
                params.append(display_name)
            if password is not None:
                updates.append("password_hash = %s")
                params.append(hash_password(password))

            new_key: str | None = None
            if reset_api_key:
                new_key = generate_api_key()
                updates.append("api_key_hash = %s")
                params.append(hash_api_key(new_key))

            if not updates:
                return UpdatedUser(user=current)

            updates.append("updated_at = now()")
            params.append(user_id)
            cur = await conn.execute(
                f"""
                UPDATE app_users
                SET {", ".join(updates)}
                WHERE id = %s
                RETURNING
                    id,
                    username,
                    display_name,
                    role,
                    is_active,
                    created_at,
                    updated_at
                """,
                params,
            )
            row = await cur.fetchone()

            if row is None:
                raise UserNotFound("用户不存在")

    return UpdatedUser(user=_row_to_user(row), api_key=new_key)
