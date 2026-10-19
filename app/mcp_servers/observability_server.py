"""只读诊断 MCP server。

把 4 个只读工具通过 MCP 协议暴露出去。Agent 那边不再 import 这些函数，
而是通过 MCP client 拿到工具定义 —— 【逻辑一份，只是暴露方式变了】。

⚠️ 为什么不把写操作也放进这个 server：
    写操作一旦注册成 MCP 工具，模型就能直接调用它，从而
    【绕过 executor 里的四道闸门】（白名单 / 参数校验 / 资源名核对 / 风险取严）。
    所以写操作永远不注册给模型，只由 executor 节点内部调用。
"""

import json

from mcp.server.fastmcp import FastMCP

from app import k8s

mcp = FastMCP("observability")


@mcp.tool()
async def query_instance_metrics(service: str, namespace: str = "prod-order") -> str:
    """查询一个服务下所有实例的【就绪状态】，用来判断是单实例异常还是整体故障。

    Args:
        service: 逻辑服务名（Pod 上 service 标签的值），例如 demo-service
        namespace: 命名空间
    """
    pods = await k8s.list_pods(service, namespace)
    return json.dumps({
        "service": service,
        "namespace": namespace,
        "instances": [
            {"instance": p["name"], "ready": p["ready"], "restarts": p["restarts"]}
            for p in pods
        ],
    }, ensure_ascii=False)


@mcp.tool()
async def get_pod_status(service: str, namespace: str = "prod-order") -> str:
    """查询一个服务的 Pod 状态与重启次数，用来判断是否处于 CrashLoopBackOff。

    Args:
        service: 逻辑服务名（Pod 上 service 标签的值），例如 demo-service
        namespace: 命名空间
    """
    pods = await k8s.list_pods(service, namespace)
    return json.dumps({
        "namespace": namespace,
        "service": service,
        "pods": pods,
    }, ensure_ascii=False)


@mcp.tool()
async def list_recent_changes(service: str, namespace: str = "prod-order",
                              window: str = "2h") -> str:
    """查询一个服务最近的发布与配置变更记录，用来判断故障是否由变更引入。

    Args:
        service: 逻辑服务名（Pod 上 service 标签的值），例如 demo-service
        namespace: 命名空间
        window: 回溯窗口，例如 30m / 2h / 24h
    """
    data = await k8s.list_recent_changes(service, namespace, window)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
async def get_rollout_status(service: str, namespace: str = "prod-order") -> str:
    """查询一个服务的发布状态，用来区分「单个实例异常」和「新版本整体起不来」。

    判断发布是否卡住时优先用它：
      - updated_replicas < desired_replicas → 发布还没完成
      - newest_replicaset.ready == 0        → 新版本从来没成功启动过
      这两种情况下重启无效，只有回滚能解除。

    Args:
        service: 逻辑服务名（Pod 上 service 标签的值），例如 demo-service
        namespace: 命名空间
    """
    resolved = await k8s.resolve_deployment(service)
    if resolved is None:
        return json.dumps({"error": f"无法解析服务 {service!r} 对应的工作负载"},
                          ensure_ascii=False)

    data = await k8s.rollout_status(resolved["namespace"], resolved["deployment"])
    return json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")