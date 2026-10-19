# app/scripts/writeback_test.py
"""验证知识回写：自动记录在不在库里、检索时排第几。"""

import asyncio

from app.rag.indexer import dump_existing
from app.rag.retriever import search_knowledge
from app.rag.writeback import AUTO_SOURCE


async def main():
    docs = dump_existing()
    auto = [d for d in docs if d.get("source") == AUTO_SOURCE]

    print(f"库里共 {len(docs)} 条，其中自动回写 {len(auto)} 条\n")
    for d in auto:
        meta = d.get("metadata") or {}
        print(f"  [{d['doc_id']}] {d['title']}")
        print(f"      service={meta.get('service')}  "
              f"occurrences={meta.get('occurrences')}  "
              f"from_fault={meta.get('from_fault_id')}")

    if not auto:
        print("（还没有自动回写的记录 —— 先跑一次能 resolved 的故障）")
        return

    meta = auto[0].get("metadata") or {}
    query = f"{meta.get('service')} 发布失败 新版本就绪探针失败 需要回滚"

    print(f"\n用「{query}」检索 top5：")
    for h in await search_knowledge(query, service=meta.get("service"), limit=5):
        mark = "★" if h["source"] == AUTO_SOURCE else " "
        print(f" {mark} [{h['score']:.4f}] {h['source']:16s} | {h['title']}")


if __name__ == "__main__":
    asyncio.run(main())