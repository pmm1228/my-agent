"""Initialize storage, optionally clearing conversation and checkpoint data."""

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.checkpointer import (
    get_checkpoint_database_url,
    init_checkpointer_storage,
    reset_checkpoint_data,
)
from app.core.database import (
    close_database,
    get_database_url,
    init_database,
    reset_chat_history_data,
)


RESET_CONFIRMATION = "RESET-CONVERSATIONS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-conversations",
        action="store_true",
        help="清空聊天会话和 LangGraph checkpoint，但保留用户与长期记忆",
    )
    parser.add_argument(
        "--confirm-reset",
        default="",
        help=f"执行清空时必须显式传入 {RESET_CONFIRMATION}",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="允许重置非本机数据库；默认仅允许 localhost/127.0.0.1",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    if args.reset_conversations and args.confirm_reset != RESET_CONFIRMATION:
        raise SystemExit(
            f"拒绝清空：请同时传入 --confirm-reset {RESET_CONFIRMATION}"
        )
    if args.reset_conversations:
        raw_targets = {
            "业务数据库": get_database_url(),
            "Checkpoint 数据库": get_checkpoint_database_url(),
        }
        targets = {
            label: urlsplit(value)
            for label, value in raw_targets.items()
            if value
        }
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        remote_targets = [
            label for label, target in targets.items()
            if target.hostname not in local_hosts
        ]
        if remote_targets and not args.allow_remote:
            raise SystemExit(
                "拒绝清空非本机数据库："
                f"{', '.join(remote_targets)}；确认目标后显式传入 --allow-remote"
            )
        for label, target in targets.items():
            print(
                f"{label}：{target.hostname or 'unknown'}:"
                f"{target.port or 5432}/{target.path.lstrip('/') or 'unknown'}"
            )
        for label, value in raw_targets.items():
            if not value:
                print(f"{label}：未配置，跳过")

    try:
        await init_database()
        await init_checkpointer_storage()
        if args.reset_conversations:
            chat_cleared = await reset_chat_history_data()
            checkpoint_cleared = await reset_checkpoint_data()
            cleared = {
                **{f"chat:{key}": value for key, value in chat_cleared.items()},
                **{
                    f"checkpoint:{key}": value
                    for key, value in checkpoint_cleared.items()
                },
            }
            details = ", ".join(
                f"{table}={count}" for table, count in sorted(cleared.items())
            )
            print(f"会话数据已清空（{details or '没有现有数据'}）")
        await init_database()
        await init_checkpointer_storage()
        print("数据库初始化完成")
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
