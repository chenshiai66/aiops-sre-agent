# app/scripts/k8s_test.py
"""验证能真的从集群里读到 Pod —— 不依赖图，也不依赖 LLM。"""

import asyncio
from app import k8s
from app.k8s import list_pods


async def main():
    pods = await list_pods("demo-service", "prod-order")
    print(f"找到 {len(pods)} 个 Pod：")
    for p in pods:
        print(f"  {p['name']:38s} phase={p['phase']:8s} "
              f"ready={str(p['ready']):5s} restarts={p['restarts']}")

    none = await list_pods("no-such-service", "prod-order")
    print(f"\n不存在的服务 -> {len(none)} 个（期望 0）")

    changes = await k8s.list_recent_changes("demo-service", "prod-order", "24h")
    print(f"\n最近 24h 变更记录：{changes['total']} 条")
    for c in changes["changes"]:
        print(f"  {c['replicaset']:32s} {c['age_seconds']:5d}s 前   {c['images']}")


if __name__ == "__main__":
    asyncio.run(main())