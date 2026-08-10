#!/usr/bin/env python3
"""CLI 入口。

用法：
  python run.py "你好"              # 单次对话
  python run.py                     # REPL 交互
  python run.py api                 # 启动 FastAPI
  python run.py api --port 9000     # 自定义端口
"""

import asyncio
import sys


def run_once(question: str):
    from app.services.chat_service import chat, close_resources

    async def _run():
        try:
            return await chat(question)
        finally:
            await close_resources()

    reply = asyncio.run(_run())
    print(reply.reply)


def run_repl():
    print("My-Agent 已启动，输入 q 退出")
    from app.services.chat_service import chat, close_resources

    thread_id = None
    while True:
        try:
            user = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in ("q", "quit", "exit"):
            break

        async def _run():
            try:
                return await chat(user, thread_id=thread_id)
            finally:
                await close_resources()

        reply = asyncio.run(_run())
        thread_id = reply.thread_id
        print(f"Bot: {reply.reply}")


def run_api(port: int = None):
    import uvicorn
    from app.core.config import get_settings

    s = get_settings()
    p = port or s.API_PORT
    uvicorn.run("app.api.main:app", host=s.API_HOST, port=p, reload=False)


def main():
    args = sys.argv[1:]

    if args and args[0] == "api":
        port = None
        for i, a in enumerate(args):
            if a == "--port" and i + 1 < len(args):
                port = int(args[i + 1])
        run_api(port)
        return

    if args:
        run_once(" ".join(args))
    else:
        run_repl()


if __name__ == "__main__":
    main()
