# app/scripts/mcp_session_test.py
"""测持久会话：用 client.session() 长期持有，看调用开销能不能降到毫秒级。"""

import asyncio
import sys
import time

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools


async def main():
    client = MultiServerMCPClient({
        "observability": {
            "command": sys.executable,
            "args": ["-m", "app.mcp_servers.observability_server"],
            "transport": "stdio",
        }
    })

    t0 = time.monotonic()
    async with client.session("observability") as session:
        tools = await load_mcp_tools(session)
        print(f"建会话 + 加载工具 {time.monotonic() - t0:.2f}s，拿到 {len(tools)} 个工具")

        pod_tool = next(t for t in tools if t.name == "get_pod_status")
        args = {"service": "demo-service", "namespace": "prod-order"}

        for i in range(4):
            t0 = time.monotonic()
            await pod_tool.ainvoke(args)
            print(f"  第 {i + 1} 次调用 {time.monotonic() - t0:.3f}s")


if __name__ == "__main__":
    asyncio.run(main())