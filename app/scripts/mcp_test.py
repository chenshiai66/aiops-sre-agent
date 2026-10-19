# app/scripts/mcp_test.py
"""验证 MCP 通道：起 server、列工具、真调一个、看数据，并测量开销。"""

import asyncio
import sys
import time

from langchain_mcp_adapters.client import MultiServerMCPClient


async def main():
    client = MultiServerMCPClient({
        "observability": {
            "command": sys.executable,
            "args": ["-m", "app.mcp_servers.observability_server"],
            "transport": "stdio",
        }
    })

    # ---------- ① 拿工具要多久 ----------
    t0 = time.monotonic()
    tools = await client.get_tools()
    t1 = time.monotonic()
    print(f"get_tools() 用了 {t1 - t0:.2f}s，拿到 {len(tools)} 个工具")

    for t in tools:
        first_line = (t.description or "").strip().splitlines()
        print(f"  - {t.name:26s} {first_line[0] if first_line else ''}")

    pod_tool = next((t for t in tools if t.name == "get_pod_status"), None)
    if pod_tool is None:
        print("\n没有找到 get_pod_status")
        return

    # ---------- ② 连续调三次，看耗时会不会掉下来 ----------
    args = {"service": "demo-service", "namespace": "prod-order"}
    times = []
    result = None
    for i in range(3):
        t0 = time.monotonic()
        result = await pod_tool.ainvoke(args)
        times.append(time.monotonic() - t0)
        print(f"  第 {i + 1} 次调用 {times[-1]:.2f}s")

    print("\n返回（原始形状）：")
    print(result)

    print("\n判断：")
    if times[-1] < times[0] / 3:
        print("  第二次开始明显变快 → 会话被复用，工具可以在进程里长期持有")
    else:
        print("  每次耗时接近 → 【每次调用都在起新子进程】，必须做持久会话或缓存")


if __name__ == "__main__":
    asyncio.run(main())