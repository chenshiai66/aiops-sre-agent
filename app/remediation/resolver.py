"""资源名解析 —— 第三条闸门。

LLM 在 planned_action.params 里填的资源名只是「意图」，不是「事实」。
执行前必须自己解析一遍，再和意图比对。

⚠️ 关键：解析过程【不使用】调用方给的 namespace。
   否则就变成"用答案验证答案"——LLM 说 default，我们就去 default 找，
   找不到就判"服务不存在"，拦下来的理由是错的。

真实路径：
    service 标签 -> Pod（跨所有命名空间）
      -> Pod.ownerReferences      -> ReplicaSet
      -> ReplicaSet.ownerReferences -> Deployment
"""

from app import k8s


async def resolve_workload(service: str) -> dict | None:
    """把逻辑服务名解析成真实工作负载。解析不出来返回 None。

    返回 {"namespace", "deployment", "replicaset", "pod"}，
    由调用方（executor）负责和 LLM 的意图比对。
    """
    if not service:
        return None
    return await k8s.resolve_deployment(service)