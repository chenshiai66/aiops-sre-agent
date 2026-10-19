"""
EscalatorAgent｜人工介入的唯一入口。

它承接两种语义：
  ① 纯交接：不暂停，直接转人工。三种来路——
       · 检索未命中 / no_action（没有动作可做）
       · 已经执行过但没成功（execution_failed / remediation_failed）
       · 命中了 forbidden 的动作（批了也不会执行，所以不批）
  ② 请求审批：有计划、该动作会改变系统、【且还没执行过】
       → interrupt() 暂停，等人决定

⚠️ interrupt() 恢复时，本节点会从头重跑。
   任何有副作用的操作必须放在 interrupt() 之后，或者做成幂等的。
   （notify() 靠 Redis SETNX 去重，所以放在 interrupt() 之前是安全的）
"""

from langgraph.types import Command, interrupt

from app.graph.state import FaultState
from app.remediation.actions import ACTIONS

from app.graph.outcome import exec_blocked
from app.notify import notify

def _reason(state: FaultState) -> str:
    # 最优先：该动手却没动成 —— 这是最需要人介入的情况
    if exec_blocked(state):
        return "execution_failed"

    if (state.get("verify_result") or {}).get("status") == "not_recovered":
        return "remediation_failed"

    if state.get("risk_level") in ("approval", "forbidden"):
        return f"risk_level={state['risk_level']}"
    if not state.get("retrieved"):
        return "no_knowledge_hit"
    return "low_score"

def _needs_approval(state: FaultState) -> bool:
    """只有「有计划」且「该动作真会改变系统」且「还没执行过」时才需要人工放行。

    四种来路只有最后一种要暂停：
      - 检索未命中（没有计划）           -> 纯交接
      - no_action（计划就是不做）        -> 纯交接
      - 已经执行过了（无论成败）          -> 纯交接（这是【升级】，不是【请求放行】）
      - 高风险动作且尚未执行             -> 审批
    """
    # ★ 已经动过手了 —— 不要再问一遍同样的事
    if state.get("exec_result"):
        return False

    plan = state.get("planned_action") or {}
    name = plan.get("name")
    if not name:
        return False

    action = ACTIONS.get(name)
    if action is None or not action.executable:
        return False
    if action.risk == "forbidden":
        return False          # 禁止的动作不该请人批准 —— 批了也不会执行

    return state.get("risk_level") in ("approval", "forbidden")


async def escalator_node(state: FaultState) -> Command:
    reason = _reason(state)

    # ---------- ① 纯交接：不需要审批 ----------
    if not _needs_approval(state):
        return Command(goto="reviewer", update={
            "escalation": {"reason": reason, "needs_approval": False},
            "audit": [{"node": "escalator", "action": "handover",
                       "reason": reason}],
        })

    # ---------- ② 请求审批：暂停等人 ----------
    plan = state.get("planned_action") or {}

    # ⚠️ 通知必须在 interrupt() 之前 —— 否则人在等的时候收不到。
    #    也正因为如此，它必须是幂等的（notify 用 Redis SETNX 去重），
    #    因为这个节点在恢复时会从头重跑。
    await notify(state, "approval_required",
                 detail=f"planned={plan.get('name')} "
                        f"risk={state.get('risk_level')}")

    # ⚠️ 这一行之前不要放任何【非幂等】的副作用


    decision = interrupt({
        "fault_id": state.get("fault_id"),
        "service": state.get("service"),
        "env": state.get("env"),
        "severity": state.get("severity"),
        "symptoms": state.get("symptoms"),
        "root_cause": state.get("root_cause"),
        "action": plan.get("name"),
        "params": plan.get("params"),
        "reversible": plan.get("reversible"),
        "analysis": plan.get("analysis"),
        "referenced_docs": plan.get("referenced_docs"),
        "risk_level": state.get("risk_level"),
    }) or {}

    approved = bool(decision.get("approved"))

    # 批准之后才是可以放副作用的地方（发通知、写工单……）
    return Command(
        goto="executor" if approved else "reviewer",
        update={
            "approval": {
                "approved": approved,
                "by": decision.get("by"),
                "comment": decision.get("comment"),
            },
            "escalation": {"reason": reason, "needs_approval": True,
                           "approved": approved},
            "audit": [{"node": "escalator", "action": "approval_decided",
                       "approved": approved, "by": decision.get("by"),
                       "planned": plan.get("name")}],
        },
    )