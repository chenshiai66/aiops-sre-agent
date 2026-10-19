from functools import lru_cache

from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient

from app.config import settings

COLLECTION = "aiops_knowledge"      # ★ 全项目唯一的 collection 名字定义


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model="text-embedding-v3",
        api_key=settings.qwen_api_key.get_secret_value(),   # ← SecretStr
        base_url=settings.dashscope_base_url,
        check_embedding_ctx_length=False,
    )