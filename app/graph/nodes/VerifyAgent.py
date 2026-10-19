"""
验证 Agent｜执行之后重新观测，确认故障是否真的恢复。

⚠️「命令执行成功」不等于「故障恢复」——
   这个节点的唯一职责就是把这两件事分开。

真实数据源：Pod 的就绪状态（app/k8s.py）。
观测窗口：滚动重启要时间，不能执行完立刻看，要轮询等一会儿。
"""

import asyncio
import time

from app import k8s
from app.graph.state import FaultState

VERIFY_TIMEOUT = 30      # 最长观察多少秒
VERIFY_INTERVAL = 3      # 每隔几秒看一次


async def _observe_until_ready(service: str, namespace: str) -> dict:
    """轮询 Pod 状态，直到【全部就绪】或超时。"""
    started = time.monotonic()
    attempts = 0
    pods: list[dict] = []

    while True:
        attempts += 1
        pods = await k8s.list_pods(service, namespace)

        if pods and all(p["ready"] for p in pods):
            break
        if time.monotonic() - started >= VERIFY_TIMEOUT:
            break

        await asyncio.sleep(VERIFY_INTERVAL)

    return {
        "pods_total": len(pods),
        "pods_ready": sum(1 for p in pods if p["ready"]),
        "attempts": attempts,
        "waited_seconds": round(time.monotonic() - started, 1),
    }


async def verify_node(state: FaultState) -> dict:
    ex = state.get("exec_result") or {}

    if ex.get("status") != "executed":
        return {
            "verify_result": {
                "status": "skipped",
                "reason": f"exec_result.status={ex.get('status')!r}，无需验证",
            },
            "audit": [{"node": "verify", "action": "skipped",
                       "reason": "nothing_executed"}],
        }

    service = state.get("service") or ""
    raw = state.get("raw_alert") or {}
    namespace = state.get("namespace") or raw.get("namespace") or ""

    if not service or not namespace:
        return {
            "verify_result": {
                "status": "unknown",
                "reason": f"缺少 service({service!r}) 或 namespace({namespace!r})",
            },
            "audit": [{"node": "verify", "action": "unknown",
                       "reason": "missing_target"}],
        }

    obs = await _observe_until_ready(service, namespace)

    recovered = obs["pods_total"] > 0 and obs["pods_ready"] == obs["pods_total"]
    result = {"status": "recovered" if recovered else "not_recovered", **obs}


    return {
        "verify_result": result,
        "audit": [{"node": "verify", "action": result["status"], **obs}],
    }