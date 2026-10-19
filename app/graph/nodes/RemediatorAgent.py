"""
修复 Agent｜读检索到的参考，从白名单里选动作，按白名单定风险等级。

它只产出计划、【不执行】—— 执行是后面 executor 的事，
中间还隔着 escalator（按风险等级决定要不要人工放行）。
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.schemas import RemediationOut
from app.graph.state import FaultState
from app.llm import get_llm
from app.remediation.actions import ACTIONS, params_help, stricter, validate_params

SYSTEM = """你是 SRE 修复决策者。根据诊断结论和检索到的运维资料，从给定的动作清单里选出一个最合适的处置动作。

规则：
- planned_action 必须从动作清单里【原样】选择一个，不允许发明清单里没有的动作名
- 参数按清单里该动作的 params 说明填写
- 如果检索到的资料互相矛盾，或信息不足以判断，就选 no_action，并在 analysis 里写清楚缺什么
- 不要因为「总得做点什么」而勉强选一个写操作
- suggested_risk 只是你的建议，最终风险等级由系统按动作清单判定
- 套用任何 runbook 之前，先确认它的【适用前提】在当前场景成立，并区分这两种故障：
    · 单个实例异常：异常实例和正常实例属于【同一个】ReplicaSet  → 重启有效
    · 新版本整体失败：异常实例属于【较新的】ReplicaSet，正常实例都在【旧的】里
      → 重启无效（它不改变镜像和配置，只会用同一个坏模板再建一个 ReplicaSet），
        只有【回滚】能解除
  判断依据直接查 rollout 状态：newest_replicaset.ready 为 0、updated_replicas < desired_replicas，
  或者 condition 出现 Progressing=False / ProgressDeadlineExceeded —— 都是"新版本整体失败"。
- 不要因为"回滚需要人工确认"就退而求其次选一个无效的动作。
  需要人拍板是【设计如此】，不是成本。选 no_action 或选高风险动作都可以，但要选【可能有效】的那个。"""


def _actions_prompt() -> str:
    lines = []
    for a in ACTIONS.values():
        p = params_help(a)
        lines.append(f"- {a.name}：{a.description}\n  参数：{p}")
    return "\n".join(lines)


def _refs_prompt(state: FaultState) -> str:
    hits = state.get("retrieved") or []
    if not hits:
        return "（没有检索到任何参考资料）"
    return "\n\n".join(
        f"[{h.get('doc_id')}] {h.get('title')}"
        f"（{h.get('source')}，相关度 {h.get('score', 0):.3f}）\n{h.get('content', '')}"
        for h in hits
    )


async def remediator_node(state: FaultState) -> dict:
    llm = get_llm().with_structured_output(RemediationOut)

    out = await llm.ainvoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=f"""## 故障诊断结论

                    现象：{state.get("symptoms", "未知")}
                    根因：{state.get("root_cause", "待确认")}
                    候选假设：{state.get("hypotheses", [])}
                    仍需确认：{state.get("missing_info", [])}
                    
                    
                    ## 故障目标（由系统解析，填参数时必须严格使用这些值，不要猜、不要自己推导）
                    
                    命名空间：{state.get("namespace") or "未知"}
                    工作负载：{state.get("deployment") or "未知"}
                    实例：{state.get("instance") or "未知"}
                    
                    ## 可用动作清单
                    
                    {_actions_prompt()}
                    
                    ## 检索到的运维资料
                    
                    {_refs_prompt(state)}
                    
                    请选出最合适的处置动作。"""),
                            ])

    # ---------- 收口 ②：动作名必须在白名单里 ----------
    action = ACTIONS.get(out.planned_action)
    if action is None:
        return _reject(out, f"动作名不在白名单：{out.planned_action}")

    # ---------- 收口 ②b：参数必须符合该动作声明的形状 ----------
    ok, params, err = validate_params(action.name, out.action_params)
    if not ok:
        return _reject(out, f"参数校验失败：{err}")

    # ---------- 收口 ③：取白名单与模型建议中更保守的那个 ----------
    final_risk = stricter(action.risk, out.suggested_risk)

    return {
        "risk_level": final_risk,
        "planned_action": {
            "name": action.name,
            "params": params,  # ← 用校验后的规范化参数，不是模型原样给的
            "reversible": action.reversible,
            "analysis": out.analysis,
            "referenced_docs": out.referenced_docs,
        },
        "audit": [{
            "node": "remediator",
            "action": "planned",
            "planned": action.name,
            "whitelist_risk": action.risk,
            "suggested_risk": out.suggested_risk,
            "final_risk": final_risk,
            "confidence": out.confidence,
        }],
    }


def _reject(out: RemediationOut, reason: str) -> dict:
    """动作名非法或参数不合法：一律转人工，不进入任何执行路径"""
    return {
        "risk_level": "approval",
        "planned_action": {
            "name": None,
            "params": out.action_params,
            "invalid": out.planned_action,
            "rejected_reason": reason,
            "analysis": out.analysis,
        },
        "audit": [{"node": "remediator", "action": "rejected",
                   "attempted": out.planned_action,
                   "attempted_params": out.action_params,
                   "reason": reason}],
    }