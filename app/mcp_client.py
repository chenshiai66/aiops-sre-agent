"""MCP 客户端 —— 长期持有会话，工具只加载一次。

⚠️ 为什么不用 MultiServerMCPClient.get_tools()：

    实测（app/scripts/mcp_session_test.py）：
        get_tools() 拿到的工具，每次 ainvoke 都重开一个子进程 ——
        第 1 次 1.30s / 第 2 次 1.31s / 第 3 次 1.36s
    而用 client.session() 长期持有：
        建会话 1.34s（一次性），之后每次调用 0.031s / 0.016s / 0.015s

⚠️⚠️ 为什么必须【显式 start()】，不能在 get_tools() 里懒加载：

    mcp 的 stdio 会话内部用 anyio 的 task group，它要求
    【建立】和【关闭】发生在【同一个任务】里。

    懒加载的话，会话会在"第一个用到工具的任务"里建立 ——
    而 LangGraph 是用 asyncio.gather 跑节点的，那是一个【新建的 Task】；
    关闭却发生在 lifespan / main()。于是报：

        RuntimeError: Attempted to exit cancel scope in a different task
                      than it was entered in

    所以：会话必须在"会负责关闭它"的那个任务里建立。
    （【使用】工具可以跨任务，这个实测过没问题。）
"""

import asyncio
import sys
from contextlib import AsyncExitStack

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

SERVERS = {
    "observability": {
        # ★ 用当前解释器，避免 PATH 里找到别的 python
        "command": sys.executable,
        "args": ["-m", "app.mcp_servers.observability_server"],
        "transport": "stdio",
    }
}

_client: MultiServerMCPClient | None = None
_stack: AsyncExitStack | None = None
_tools: list = []
_lock = asyncio.Lock()


async def start() -> list:
    """建立 MCP 会话并加载工具。幂等，可以重复调用。

    ⚠️ 必须在【会调用 close() 的那个任务】里调用。原因见模块 docstring。
    """
    global _client, _stack, _tools

    async with _lock:
        if _tools:
            return _tools

        _client = MultiServerMCPClient(SERVERS)
        _stack = AsyncExitStack()
        session = await _stack.enter_async_context(
            _client.session("observability"))
        _tools = await load_mcp_tools(session)
        return _tools


def get_tools() -> list:
    """取已加载的工具。必须先 start()。

    故意做成【同步】的：工具在 start() 时就固定了，节点里只是取一下。
    取不到就直接抛 —— 让"忘了 start()"立刻暴露，而不是悄悄走一条新路径。
    """
    if not _tools:
        raise RuntimeError(
            "MCP 会话还没建立 —— 在调用图之前先 await mcp_client.start()")
    return _tools


async def close() -> None:
    """关闭会话。幂等。"""
    global _client, _stack, _tools
    if _stack is not None:
        await _stack.aclose()
    _client, _stack, _tools = None, None, []