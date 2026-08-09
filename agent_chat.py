#!/usr/bin/env python3
"""兼容入口。

项目主实现已经收敛到 app/ 目录；继续支持 `python agent_chat.py ...`
是为了兼容早期用法。
"""

from run import main, run_once, run_repl


__all__ = ["main", "run_once", "run_repl"]


if __name__ == "__main__":
    main()
