from langgraph.checkpoint.redis import AsyncRedisSaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes.DetectorAgent import detector_node
from app.graph.nodes.DispatcherAgent import dispatcher_node
from app.graph.nodes.EscalatorAgent import escalator_node
from app.graph.nodes.RemediatorAgent import remediator_node
from app.graph.nodes.RetrieverAgent import retriever_node
from app.graph.nodes.ReviewerAgent import reviewer_node
from app.graph.nodes.ExecutorAgent import executor_node
from app.graph.nodes.VerifyAgent import verify_node
from app.graph.state import FaultState

from app.graph.outcome import exec_blocked



# ★ 占位值，不是调优结果。
#   等知识库重灌完，看 rag_search_test.py 打出的真实分数再定这个数。
RETRIEVAL_THRESHOLD = 0.5


def route_after_retrieve(state: FaultState) -> str:
    """检索之后：命中且分数够 → 处置；否则 → 转人工。"""
    hits = state.get("retrieved") or []
    if not hits:
        return "escalator"
    if hits[0].get("score", 0.0) < RETRIEVAL_THRESHOLD:
        return "escalator"
    return "remediator"


def route_after_remediate(state: FaultState) -> str:
    """

        处置之后：低风险 → 执行器；需要审批或禁止 → 转人工。
    """
    if state.get("risk_level") in ("approval", "forbidden"):
        return "escalator"
    return "executor"



def route_after_verify(state: FaultState) -> str:
    """验证之后：
       · 该动手却没动成   → 必须让人知道（人可能已经批准过了）
       · 执行了但没修好   → 必须让人知道
       · 其余             → 正常收尾
    """
    if exec_blocked(state):
        return "escalator"

    verify = state.get("verify_result") or {}
    if verify.get("status") == "not_recovered":
        return "escalator"

    return "reviewer"


def _build_state_graph() -> StateGraph:
    graph = StateGraph(FaultState)

    graph.add_node("dispatcher", dispatcher_node)
    graph.add_node("detector", detector_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("remediator", remediator_node)
    graph.add_node("executor", executor_node)
    graph.add_node("verify", verify_node)
    graph.add_node("escalator", escalator_node)
    graph.add_node("reviewer", reviewer_node)

    graph.add_edge(START, "dispatcher")
    graph.add_edge("dispatcher", "detector")
    graph.add_edge("detector", "retriever")

    graph.add_conditional_edges("retriever", route_after_retrieve, {
        "remediator": "remediator",
        "escalator": "escalator",
    })
    graph.add_conditional_edges("remediator", route_after_remediate, {
        "escalator": "escalator",
        "executor": "executor",
    })
    graph.add_edge("executor", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {
        "escalator": "escalator",
        "reviewer": "reviewer",
    })
    graph.add_edge("reviewer", END)

    return graph


async def build_graph(redis_url: str):
    """构建入口：绑定 Redis checkpoint 持久化"""
    saver = AsyncRedisSaver(redis_url)
    await saver.asetup()

    graph = _build_state_graph()
    return graph.compile(checkpointer=saver)