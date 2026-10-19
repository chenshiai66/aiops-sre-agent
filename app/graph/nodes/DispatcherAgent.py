"""
DispatcherAgent｜归一化原始告警。

它负责把告警里的【逻辑名字】翻译成系统里的【真实名字】：
    service（demo-service）  ->  deployment（order-svc）

为什么要在这里做：
    告警里的 service 是监控系统的逻辑标签，
    而 K8s 里的 Deployment 可能叫别的名字。这个映射是【系统已知的事实】，
    不该让 LLM 去猜 —— 上一轮它就是猜错成 demo-service 的。
"""

from app import k8s
from app.graph.state import FaultState


async def dispatcher_node(state: FaultState) -> dict:
    alert = state.get("raw_alert", {})
    service = alert.get("service", "unknown")

    # 解析真实工作负载。解析不出来不阻断流程，交给后面的闸门去拒绝。
    resolved = await k8s.resolve_deployment(service) or {}

    return {
        "service":    service,
        "env":        alert.get("env", "prod"),
        "severity":   alert.get("severity", "P3"),
        "namespace":  alert.get("namespace") or resolved.get("namespace") or "",
        "instance":   alert.get("instance") or "",
        "deployment": resolved.get("deployment") or "",
        "audit": [{"node": "dispatcher", "action": "normalized",
                   "deployment": resolved.get("deployment")}],
    }