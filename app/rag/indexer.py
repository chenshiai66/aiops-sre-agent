
import asyncio
import uuid

from qdrant_client.models import Distance, PointStruct, VectorParams

from app.rag.client import COLLECTION, get_client, get_embeddings

POINT_NS = uuid.UUID("6f1d0e3a-0000-4000-8000-000000000001")
EMBED_BATCH = 10          # DashScope text-embedding-v3 单次上限


async def embed_all(docs: list[dict]) -> list[list[float]]:
    """先把所有向量算完 —— 所有网络失败都发生在这里，不碰数据库"""
    emb = get_embeddings()
    texts = [f"{d.get('title', '')}\n{d.get('content', '')}" for d in docs]

    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        chunk = texts[i:i + EMBED_BATCH]
        vectors.extend(await emb.aembed_documents(chunk))
        print(f"  embedded {min(i + EMBED_BATCH, len(texts))}/{len(texts)}")
    return vectors


async def recreate_collection() -> int:
    """重建 collection。维度从模型实测，不再硬编码。"""
    probe = await get_embeddings().aembed_query("dimension probe")
    size = len(probe)
    print(f"embedding 维度实测 = {size}")

    client = get_client()
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=size, distance=Distance.COSINE),
    )
    print("collection 已重建")
    return size


async def upsert_documents(docs: list[dict], vectors: list[list[float]]) -> int:
    if len(docs) != len(vectors):
        raise RuntimeError(f"文档 {len(docs)} 条 != 向量 {len(vectors)} 条，中止")

    points = []
    for d, v in zip(docs, vectors):
        doc_id = d.get("doc_id")
        if not doc_id:
            raise ValueError(f"文档缺 doc_id: {d.get('title')!r}")
        points.append(PointStruct(
            id=str(uuid.uuid5(POINT_NS, doc_id)),
            vector=v,
            payload={
                "doc_id":   doc_id,
                "title":    d.get("title", ""),
                "source":   d.get("source", ""),
                "content":  d.get("content", ""),
                "metadata": d.get("metadata") or {},
            },
        ))

    # 同步客户端 → 丢进线程池，别卡事件循环
    await asyncio.to_thread(
        get_client().upsert, collection_name=COLLECTION, points=points)
    return len(points)


def dump_existing() -> list[dict]:
    """把现有 collection 的 payload 全捞出来（只要正文，不要向量）"""
    client = get_client()
    docs, offset = [], None
    while True:
        batch, offset = client.scroll(
            collection_name=COLLECTION, limit=100,
            with_payload=True, with_vectors=False, offset=offset,
        )
        for p in batch:
            docs.append({
                "doc_id":   p.payload.get("doc_id") or str(p.id),
                "title":    p.payload.get("title", ""),
                "source":   p.payload.get("source", ""),
                "content":  p.payload.get("content", ""),
                "metadata": p.payload.get("metadata") or {},
            })
        if offset is None:
            break
    return docs


async def reindex(docs: list[dict]) -> None:
    vectors = await embed_all(docs)          # ① 最危险的一步放最前
    print(f"向量就绪 {len(vectors)} 条")

    await recreate_collection()               # ② 确认没问题了才动库
    n = await upsert_documents(docs, vectors)       # ③ 写入
    print(f"重新索引 {n} 条")


async def reindex_from_existing() -> None:
    """⚠️ 会先读后删，只在 collection 里确实有数据时用"""
    await reindex(dump_existing())


if __name__ == "__main__":
    from app.rag.seed import DOCS
    from app.rag.writeback import AUTO_SOURCE

    # ⚠️ reindex() 会删掉整个 collection 再重建。
    #    必须先把自动回写的记录捞出来一起写回去，
    #    否则每次重灌种子数据都会把 Agent 学到的东西擦掉。
    auto = [d for d in dump_existing() if d.get("source") == AUTO_SOURCE]
    print(f"保留自动回写记录 {len(auto)} 条")
    asyncio.run(reindex(DOCS + auto))