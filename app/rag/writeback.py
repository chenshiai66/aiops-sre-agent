
"""知识回写 —— 把一次故障处置的结论沉淀回知识库。

这是「自进化」的入口：Agent 修好一个故障之后，把这次的判断和结果
写进 Qdrant，下次遇到同类故障时能被检索到。

⚠️ 三条自我约束（都是为了防止知识库被污染）：

① 只回写 outcome == "resolved"
   为什么不写 failed？—— 失败的原因可能是【我们自己代码的 bug】，
   而不是这个动作本身不对。写进去等于教未来的自己"别用这个动作"。
   这种"把工具缺陷记成领域知识"的污染，是自进化系统最危险的失败模式。

② 只记录当时的事实，不做二次总结
   写进去的每个字都来自 state 里已有的字段。不让 LLM 再"润色"一遍 ——
   知识库内容会被未来的自己当成事实引用，在回写这步再生成文本就是制造幻觉。

③ 用稳定的 doc_id 覆盖，不无限堆积
   doc_id 由 service + alertname + action 拼成，同类故障是【更新同一条】。
   indexer 用 uuid5(doc_id) 做点 ID，天然幂等。
"""

import uuid
import asyncio
from app.rag.client import COLLECTION, get_client
from app.rag.indexer import POINT_NS, embed_all, upsert_documents

AUTO_SOURCE = "auto-review"

# 什么结局才值得写进知识库。见模块 docstring 的 ①。
WRITABLE_OUTCOMES = {"resolved"}


def _build_content(state: dict) -> str:
    """按固定模板拼装。每个值都直接取自 state，不做任何加工。"""
    alert = state.get("raw_alert") or {}
    plan = state.get("planned_action") or {}
    verify = state.get("verify_result") or {}
    hypotheses = state.get("hypotheses") or []
    hyp_lines = "\n".join(f"  - {h}" for h in hypotheses) or "  （无）"

    return "\n".join([
        "【告警】",
        f"  alertname={alert.get('alertname')}  service={alert.get('service')}  "
        f"namespace={alert.get('namespace')}  instance={alert.get('instance')}",
        f"  metric={alert.get('metric')}  value={alert.get('value')}  "
        f"threshold={alert.get('threshold')}  severity={alert.get('severity')}",
        "",
        "【当时观察到的现象】",
        f"  {state.get('symptoms')}",
        "",
        "【当时判断的根因】",
        f"  {state.get('root_cause')}",
        "",
        "【当时的候选假设】",
        hyp_lines,
        "",
        "【实际执行的动作】",
        f"  {plan.get('name')}  params={plan.get('params')}",
        "",
        "【执行后的验证】",
        f"  {verify.get('pods_ready')}/{verify.get('pods_total')} 个副本就绪，"
        f"观测 {verify.get('waited_seconds')} 秒",
        "",
        "【结论】",
        "  ✅ 该处置有效，故障已恢复。",
        f"  （本条由系统自动回写，source={AUTO_SOURCE}，未经人工复核）",
    ])


async def _next_occurrences(doc_id: str) -> int:
    """同一条记录被写到第几次了。"""
    pid = str(uuid.uuid5(POINT_NS, doc_id))
    got = await asyncio.to_thread(
        get_client().retrieve,
        collection_name=COLLECTION, ids=[pid], with_payload=True)
    if not got:
        return 1
    meta = got[0].payload.get("metadata") or {}
    return int(meta.get("occurrences") or 0) + 1


def build_entry(state: dict) -> dict:
    alert = state.get("raw_alert") or {}
    plan = state.get("planned_action") or {}
    service = state.get("service") or "unknown"
    alertname = alert.get("alertname") or "UnknownAlert"
    action = plan.get("name") or "none"

    doc_id = f"auto-{service}-{alertname}-{action}"

    return {
        "doc_id": doc_id,
        "title": f"故障复盘：{service} {alertname}（{action} 处置有效）",
        "source": AUTO_SOURCE,
        "content": _build_content(state),
        "metadata": {
            # ★ 必须写 service，否则会被检索当成"不绑定服务的通用知识"
            "service": service,
            "from_fault_id": state.get("fault_id"),
            "outcome": state.get("outcome"),
            "action": action,
            "occurrences": 1,
        },
    }


async def write_back(state: dict) -> dict:
    """把这次的处置结论写回知识库。

    返回一个小字典，会存进 state["knowledge_entry"]。
    ⚠️ 绝不抛异常 —— 回写失败不能影响故障处置的收尾。
    """
    outcome = state.get("outcome")
    if outcome not in WRITABLE_OUTCOMES:
        return {"written": False,
                "reason": f"outcome={outcome!r} 不产生可复用的新知识"}

    try:
        entry = build_entry(state)
        entry["metadata"]["occurrences"] = await _next_occurrences(entry["doc_id"])

        vectors = await embed_all([entry])
        await upsert_documents([entry], vectors)

        return {
            "written": True,
            "doc_id": entry["doc_id"],
            "source": AUTO_SOURCE,
            "occurrences": entry["metadata"]["occurrences"],
        }
    except Exception as exc:
        return {"written": False, "reason": f"回写失败：{exc}"}