# app/scripts/resolver_test.py
"""资源名解析的独立验证 —— 只读，不碰任何东西。"""

import asyncio

from app.remediation.resolver import resolve_workload


async def main():
    cases = [
        ("demo-service", "应该解析出来"),
        ("no-such-service", "应该解析不出来"),
    ]

    for service, note in cases:
        r = await resolve_workload(service)
        print(f"{service:20s} -> {r}    （{note}）")


if __name__ == "__main__":
    asyncio.run(main())