# app/scripts/rollout_test.py
"""发布状态的独立验证。"""

import asyncio
import json

from app import k8s


async def main():
    status = await k8s.rollout_status("prod-order", "order-svc")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())