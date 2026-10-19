from qdrant_client.models import FieldCondition, Filter, IsEmptyCondition, MatchValue, PayloadField
import asyncio
from app.rag.client import COLLECTION, get_client, get_embeddings



async def search_knowledge(
    query: str,
    *,
    service: str | None = None,
    source: str | None = None,
    limit: int = 3,
) -> list[dict]:
    vec = await get_embeddings().aembed_query(query)

    must = []
    if source:
        must.append(FieldCondition(key="source", match=MatchValue(value=source)))

    query_filter = None
    if service:
        # 本服务的知识 OR 不绑定服务的通用手册
        query_filter = Filter(
            must=must,
            should=[
                FieldCondition(key="metadata.service", match=MatchValue(value=service)),
                IsEmptyCondition(is_empty=PayloadField(key="metadata.service")),
            ],
        )
    elif must:
        query_filter = Filter(must=must)


    # ⚠️ Qdrant 客户端是【同步阻塞】的 —— 在 async 函数里直接调会卡住整个事件循环。
    #    一次查询几十毫秒看着不多，但它是【每个故障】都要走的一步。
    #    app/k8s.py 的模块 docstring 专门写过这件事，RAG 层之前漏了。
    resp = await asyncio.to_thread(
        get_client().query_points,
        collection_name=COLLECTION,
        query=vec,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )

    return [
        {
            "doc_id":  p.payload.get("doc_id"),
            "title":   p.payload.get("title"),
            "source":  p.payload.get("source"),
            "content": p.payload.get("content"),
            "meta":    p.payload.get("metadata") or {},
            "score":   p.score,
        }
        for p in resp.points
    ]


