"""待审批故障的索引。

为什么需要它：
    checkpoint 是按 thread_id（= fault_id）存的，**只能按 id 查，不能列举**。
    所以"现在有哪些故障在等我批"这个问题，光靠 checkpoint 回答不了。

它是什么：
    一个 fault_id 的集合。
    ⚠️ 它不是权威数据 —— 真正决定"还能不能审批"的仍然是 checkpoint 里的
       next 是否为空（main.py:80 那个 409 检查）。这里只是个索引。
"""

import redis.asyncio as aioredis

PENDING_KEY = "faults:pending"


class PendingIndex:
    def __init__(self, redis_url: str):
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def add(self, fault_id: str) -> None:
        await self._redis.sadd(PENDING_KEY, fault_id)

    async def remove(self, fault_id: str) -> None:
        await self._redis.srem(PENDING_KEY, fault_id)

    async def list_all(self) -> list[str]:
        return sorted(await self._redis.smembers(PENDING_KEY))

    async def contains(self, fault_id: str) -> bool:
        """这条故障在不在待审批集合里 —— GET /faults/{id} 用它区分状态。"""
        return bool(await self._redis.sismember(PENDING_KEY, fault_id))