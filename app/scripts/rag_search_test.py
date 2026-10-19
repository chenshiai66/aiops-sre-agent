# app/scripts/rag_search_test.py
import asyncio

from qdrant_client.models import (FieldCondition, Filter, IsEmptyCondition,
                                  MatchValue, PayloadField)
from app.rag.client import COLLECTION
from app.rag.client import get_client, get_embeddings



QUERY = ("order-svc 单实例 HTTP 5xx 比例 23%，超过 5% 阈值，持续 5 分钟，"
         "疑似下游依赖超时或实例资源饱和")


async def main():
    vec = await get_embeddings().aembed_query(QUERY)
    client = get_client()

    # ① 不带过滤，看真实分数分布
    resp = client.query_points(collection_name=COLLECTION, query=vec,
                               limit=10, with_payload=True)
    print("=== 无过滤 top10 ===")
    for p in resp.points:
        m = p.payload.get("metadata") or {}
        print(f"  [{p.score:.4f}] {str(m.get('service')):14s} "
              f"{str(p.payload.get('source')):16s} {p.payload.get('title')}")

    # ② 三种过滤策略对比
    print("\n=== 过滤对比 ===")
    SERVICE = "demo-service"
    strategies = {
        "无过滤": None,
        "严格(只本服务)": Filter(must=[
            FieldCondition(key="metadata.service", match=MatchValue(value=SERVICE)),
        ]),
        "本服务OR通用": Filter(should=[
            FieldCondition(key="metadata.service", match=MatchValue(value=SERVICE)),
            IsEmptyCondition(is_empty=PayloadField(key="metadata.service")),
        ]),
    }
    for name, f in strategies.items():
        r = client.query_points(collection_name=COLLECTION, query=vec,
                                query_filter=f, limit=6, with_payload=True)
        print(f"\n[{name}] {len(r.points)} 条")
        for p in r.points:
            m = p.payload.get("metadata") or {}
            print(f"   [{p.score:.4f}] {str(m.get('service')):14s} "
                  f"{p.payload.get('title')}")

if __name__ == "__main__":
    asyncio.run(main())