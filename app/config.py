from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",                    # .env 里有未声明的变量时不报错
    )

    # ---- Redis / Qdrant ----
    redis_url: str = "redis://localhost:6379/0"
    # ⚠️ Qdrant 用 6343（不是默认的 6333）—— 和 docker-compose.yml 保持一致。
    #    6333 留给本机另一个项目的 qdrant，两个项目互不干扰。
    qdrant_url: str = "http://localhost:6343"

    # ---- LLM / Embedding (DashScope) ----
    # 两个 key 都来自 DashScope，故意分开用在两条链路上：
    #   dashscope_api_key -> LLM 对话     （app/llm.py）
    #   qwen_api_key      -> 向量化 embedding（app/rag/client.py）
    # 分开的好处是两条链路的配额/计费可以独立观察；
    # 如果确认两把钥匙等价，把其中一处改成同一个字段即可。
    #
    # SecretStr：即使手滑 print(settings.model_dump()) 也只会显示 **********。
    dashscope_api_key: SecretStr = SecretStr("")
    qwen_api_key: SecretStr = SecretStr("")
    dashscope_base_url: str = ""


settings = Settings()
