"""
执行 Agent｜把已通过全部校验的处置计划变成真实动作。

⚠️ 这个节点没有 LLM，是纯执行节点。
   命名沿用 xxxAgent.py 的约定只是为了和其余节点保持一致。
"""

from app.graph.state import FaultState
from app.remediation.executor import execute


async def executor_node(state: FaultState) -> dict:
    plan = state.get("planned_action") or {}
    action_name = plan.get("name")

    if not action_name:
        return {
            "exec_result": {"status": "rejected", "reason": "没有可执行的计划"},
            "audit": [{"node": "executor", "action": "rejected",
                       "reason": "no_planned_action"}],
        }

    result = await execute(action_name, plan.get("params") or {},
                           state.get("service", ""))

    return {
        "exec_result": result,
        "audit": [{
            "node": "executor",
            "action": result.get("status"),
            "planned": action_name,
            "reason": result.get("reason"),
        }],
    }