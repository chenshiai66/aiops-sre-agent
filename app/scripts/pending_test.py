# app/scripts/pending_test.py
"""待审批索引的独立验证 —— 不依赖图，也不依赖服务。"""

import asyncio

from app.config import settings
from app.pending import PendingIndex


async def main():
    idx = PendingIndex(settings.redis_url)

    # 先清干净，保证结果可重复
    for fid in ("demo-1", "demo-2"):
        await idx.remove(fid)

    print("初始          :", await idx.list_all())

    await idx.add("demo-1")
    await idx.add("demo-2")
    print("加两条后      :", await idx.list_all())

    await idx.add("demo-1")          # 故意重复加
    print("重复加 demo-1 :", await idx.list_all(), "← 应该还是 2 条")

    await idx.remove("demo-1")
    print("移除 demo-1   :", await idx.list_all())

    await idx.remove("demo-2")
    print("清空后        :", await idx.list_all())


if __name__ == "__main__":
    asyncio.run(main())