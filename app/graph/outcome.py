"""结局判定 —— 全局唯一的一份。

⚠️ 为什么要单独放一个文件：

    这个项目出过两次「同一个事实，两个函数判断相反」的 bug：
      · _reason() 认识"执行过了"，_needs_approval() 不认识  → 审批循环
      · reviewer 的 outcome 和 escalator 的 reason 各判一次 → 理由错位

    所以凡是「多个节点都要用的状态判断」，都放这里，只写一遍。
"""

from app.graph.state import FaultState


def exec_blocked(state: FaultState) -> bool:
    """「该动手，却没动成」—— 这是必须让人知道的状态。

    两种来源：
      ① executor 抛了异常          （exec_result.status == "error"）
      ② 人工已批准，但被执行闸门拦下（status == "rejected" 且 approval.approved）

    第二种最容易被忽略：**人批准之后是等着结果的**，
    哪怕系统出于安全考虑拒绝了，也必须告诉他"没有执行"。
    """
    ex = state.get("exec_result") or {}
    status = ex.get("status")

    if status == "error":
        return True

    approved = (state.get("approval") or {}).get("approved") is True
    return approved and status == "rejected"



def compute_outcome(state: FaultState) -> str:
    """这次故障【最后怎么了】—— 全局唯一的一份判定。

    ⚠️ 分支顺序是有意义的，不能随意调整：

        · human_rejected 必须最先判
          —— 那是人自己的决定，和系统行为无关

        · exec_blocked 必须排在 gate_rejected 【之前】
          —— "人批准了但被拦下"要先于"被闸门拦下"被识别。
             排反了，前者会被记成 rejected，就是我们要修的那个 bug
    """
    plan = state.get("planned_action") or {}
    ex = state.get("exec_result") or {}
    verify = state.get("verify_result") or {}

    ex_status = ex.get("status")
    v_status = verify.get("status")

    gate_rejected = bool(plan.get("rejected_reason") or plan.get("invalid")) \
                    or ex_status == "rejected"
    human_rejected = (state.get("approval") or {}).get("approved") is False

    if human_rejected:
        return "rejected"          # 人自己否决的，他知道
    if exec_blocked(state):
        return "exec_error"        # 该动手却没动成 —— 必须让人知道
    if gate_rejected:
        return "rejected"          # 机器闸门拦下，没人等着结果
    if v_status == "recovered":
        return "resolved"
    if v_status == "not_recovered":
        return "failed"            # 执行了，但故障没恢复
    if ex_status == "executed":
        return "unverified"        # 执行了，但没有验证结果
    if state.get("escalation"):
        return "escalated"         # 转人工，系统没有动手
    return "noop"