"""动作执行器 —— 最后一道闸门。

这里是「计划」变成「现实」的地方，所以有三条硬规则：
  1. 资源名必须自己解析，不信 LLM 填的
  2. 解析结果和 LLM 的意图不一致 → 拒绝执行
  3. 不管成功还是失败，都返回结构化结果，不抛异常

status 取值（三者的区别很重要，下游靠它决定要不要惊动人）：
    executed   已执行（真实 K8s 操作）
    rejected   被闸门【主动】拦下，没动手 —— 这是安全设计
    error      想动手但没做成（异常 / 该动作还没实现）
"""
from app.remediation.actions import ACTIONS
from app.remediation.resolver import resolve_workload
from app import k8s

async def resolve_and_check(action_name: str, params: dict,
                            service: str) -> tuple[dict | None, dict | None]:
    """跑完所有闸门，并解析出真实资源。

    返回 (real_params, None)  → 放行，可以执行
    返回 (None, 拒绝结果)      → 被拦下

    ⚠️ 这个函数【只读】—— 它只解析资源、比对意图，不做任何写操作。
       所以测试可以随意调用它，不会动到集群。
       真正的写操作在 _perform() 里，只有这里放行之后才会走到。

    ⚠️ 这也是它为什么和 execute() 分开：
       以前闸门和写操作在一个函数里，导致"验证闸门"的测试
       【每跑一次就真的重启一次生产 Deployment】。
       一个会改生产状态的测试，是不可能被放心重跑的 ——
       而"随时能重跑"是测试的基本要求。
    """
    # ---------- 闸门 1：动作必须在白名单里 ----------
    action = ACTIONS.get(action_name)
    if action is None:
        return None, {"status": "rejected", "reason": f"未知动作：{action_name}"}

    # ---------- 闸门 2：兜底拦一次 forbidden ----------
    # 即使上游漏了风险判定，这里也要拦
    if action.risk == "forbidden":
        return None, {"status": "rejected",
                      "reason": f"{action_name} 属于禁止执行的动作"}

    # ---------- 闸门 3：解析真实资源，并和 LLM 的意图比对 ----------
    resolved = await resolve_workload(service)
    if resolved is None:
        return None, {"status": "rejected",
                      "reason": f"无法解析服务 {service!r} 对应的工作负载"}

    namespace = params.get("namespace", "")
    if namespace and resolved["namespace"] != namespace:
        return None, {"status": "rejected",
                      "reason": f"命名空间不一致：意图 {namespace!r}，"
                                f"实际解析为 {resolved['namespace']!r}"}

    intent_deployment = params.get("deployment")
    if intent_deployment and resolved["deployment"] != intent_deployment:
        return None, {"status": "rejected",
                      "reason": f"资源名不一致：意图 {intent_deployment!r}，"
                                f"实际解析为 {resolved['deployment']!r}"}

    # 放行：把解析出来的真实值注入参数，覆盖 LLM 填的
    return {**params,
            "namespace": resolved["namespace"],
            "deployment": resolved["deployment"]}, None


async def execute(action_name: str, params: dict, service: str) -> dict:
    """执行一个动作：先过闸门，放行才真动手。

    status 取值：
        executed   已执行（真实 K8s 操作）
        rejected   被闸门主动拦下，没动手
        error      想动手但没做成
    """
    real_params, rejection = await resolve_and_check(action_name, params, service)
    if rejection is not None:
        return rejection

    return await _perform(action_name, real_params)


async def _perform(action_name: str, params: dict) -> dict:
    """真正的执行入口。

    真实系统会失败（资源不存在、权限不足、版本对不上……），
    所以这里必须兜住异常 —— 不能让一个 K8s 报错把整张图打崩。
    """
    try:
        # ⚠️ 取参数也放在 try 里 —— 上游保证会注入 namespace，
        #    但"上游保证"不是兜底：少一个 key 就让整张图崩掉，代价太大。
        namespace = params["namespace"]

        if action_name == "restart_deployment":
            result = await k8s.rollout_restart(namespace, params["deployment"])
        elif action_name == "scale_up":
            result = await k8s.scale_deployment(
                namespace, params["deployment"], int(params["replicas"]))
        elif action_name == "rollback_deployment":
            result = await k8s.rollback_deployment(
                namespace, params["deployment"], params.get("revision", ""))
        else:
            return {"status": "error",
                    "reason": f"{action_name} 尚未接入真实执行"}
    except Exception as exc:
        msg = str(exc)
        if len(msg) > 400:
            msg = msg[:400] + " …（已截断）"
        return {"status": "error",
                "reason": f"执行失败（{action_name}）：{msg}"}

    return {"status": "executed", "action": action_name,
            "params": params, "result": result}