"""
复盘 Agent｜判定结局，并把结论沉淀回知识库。

⚠️ 结局判定的逻辑【不在这里】，在 app/graph/outcome.py。
   原因：它要被 escalator 和 reviewer 共用，而且需要能被单元测试覆盖。
   放在节点内部的话，"分支顺序写错"这种 bug 测不到 —— 而这类 bug 已经出过两次。
"""
from app.graph.outcome import compute_outcome
from app.graph.state import FaultState
from app.rag.writeback import write_back
from app.notify import notify




def _notify_detail(state: dict, outcome: str) -> str:
    """给通知写一句人话说明。不同结局关心的东西不一样。"""
    ex = state.get("exec_result") or {}
    vr = state.get("verify_result") or {}
    esc = state.get("escalation") or {}

    if outcome == "exec_error":
        return ex.get("reason") or "执行未成功"
    if outcome == "failed":
        return (f"{vr.get('pods_ready')}/{vr.get('pods_total')} 个副本就绪，"
                f"观测 {vr.get('waited_seconds')} 秒后仍未恢复")
    if outcome == "resolved":
        plan = state.get("planned_action") or {}
        return (f"{plan.get('name')} 生效，"
                f"{vr.get('pods_ready')}/{vr.get('pods_total')} 个副本就绪")
    if outcome == "escalated":
        return f"原因：{esc.get('reason')}"
    return ""




async def reviewer_node(state: FaultState) -> dict:
    outcome = compute_outcome(state)


    # 终态通知。不在 EVENTS 表里的 outcome（rejected / unverified / noop）
    # 会被 notify 直接跳过 —— 不需要在这里判断。
    notification = await notify(state, outcome, detail=_notify_detail(state, outcome))

    # 把结论沉淀回知识库。outcome 此刻还没写进 state，所以手动带上。
    knowledge = await write_back({**state, "outcome": outcome})

    return {
        "outcome": outcome,
        "knowledge_entry": knowledge,
                "audit": [{"node": "reviewer", "action": "reviewed",
                   "outcome": outcome, "knowledge": knowledge,
                   "notification": notification}],
    }