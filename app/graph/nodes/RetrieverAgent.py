"""
RAG 检索 Agent｜检索运维知识库、历史故障工单，返回参考案例、运维手册
"""
from app.rag.retriever import search_knowledge
from app.graph.state import FaultState

async def retriever_node(state: FaultState) -> dict:
    query = _build_query(state)
    hits = await search_knowledge(query, service=state.get("service"), limit=5)
    return {
        "retrieved": hits,
        "audit": [{"node": "retriever", "action": "searched",
                   "hits": len(hits),
                   "top_score": hits[0]["score"] if hits else None}],
    }


def _build_query(state: FaultState) -> str:
    parts = [state.get("symptoms", "")]
    parts += [h[:30] for h in state.get("hypotheses", [])[:3]]   # ← 截断
    return "\n".join(p for p in parts if p)