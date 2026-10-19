# app/scripts/embed_diag.py
import asyncio
import math

from app.rag.client import COLLECTION, get_client, get_embeddings




def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def norm(v):
    return math.sqrt(sum(x * x for x in v))


async def main():
    emb = get_embeddings()

    # ---------- A. 纯模型：一对明显相关的文本，完全不碰数据库 ----------
    q = "服务不可用 HTTP 5xx 503 错误率飙升"
    d = ("运维手册：服务不可用（5xx / 503）标准处置流程。"
         "适用范围：服务错误率上升、返回 503/502、健康检查失败。")

    vq = await emb.aembed_query(q)
    vd = await emb.aembed_query(d)
    print("A. 相关文本对 cosine  =", round(cos(vq, vd), 4))
    print("   向量 norm          =", round(norm(vq), 4), "维度 =", len(vq))

    # ---------- B. 索引一致性：库里存的向量 vs 现在重新算的 ----------
    client = get_client()
    pts, _ = client.scroll(collection_name=COLLECTION, limit=1,
                           with_payload=True, with_vectors=True)

    if not pts:
        print("\nB. 跳过 —— collection 是空的，先跑 python -m app.rag.indexer")
        return

    p = pts[0]
    text = p.payload.get("content") or ""
    stored, fresh = p.vector, await emb.aembed_query(text)

    print("\nB. 库里向量 vs 重算    =", round(cos(fresh, stored), 4))
    print("   库里 norm          =", round(norm(stored), 4))
    print("   重算 norm          =", round(norm(fresh), 4))


if __name__ == "__main__":
    asyncio.run(main())