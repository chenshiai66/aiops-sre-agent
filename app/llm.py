from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import settings


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model="qwen-plus",
        api_key=settings.dashscope_api_key.get_secret_value(),
        base_url=settings.dashscope_base_url,
        temperature=0,                            # 运维场景要可复现
        timeout=30,                               # 网络调用必须有超时
        max_retries=2,
    )
