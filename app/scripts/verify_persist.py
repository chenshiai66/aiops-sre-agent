"""
持久化验证 —— 看一条故障的 checkpoint 状态和【逐步历史】。

用法：
    python -m app.scripts.verify_persist <fault_id>

为什么它值得留着：
    checkpoint 是整个项目的地基（跨进程恢复、中断续跑全靠它）。
    aget_state_history 能打出每一步的 step 和 next ——
    排查"图为什么停在某一步"时，这比单点快照有用得多，
    而且没有任何别的脚本做这件事。
"""

import asyncio
import sys

from app.config import settings
from app.graph.builder import build_graph


async def main(fault_id: str) -> None:
    # 用 settings.redis_url，不要硬编码 —— 否则 .env 一改，
    #    这个脚本和服务就连到了【不同的库】，查出来的东西对不上。
    graph = await build_graph(settings.redis_url)
    cfg = {"configurable": {"thread_id": fault_id}}

    snap = await graph.aget_state(cfg)
    print("outcome:", snap.values.get("outcome"))
    print("audit  :", len(snap.values.get("audit", [])))
    print("next   :", snap.next)

    print("--- history ---")
    async for s in graph.aget_state_history(cfg):
        print(f"step={s.metadata.get('step')}  next={s.next}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1]:
        raise SystemExit("用法: python -m app.scripts.verify_persist <fault_id>")
    asyncio.run(main(sys.argv[1]))