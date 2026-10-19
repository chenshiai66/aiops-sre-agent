"""和 Kubernetes API 打交道的唯一入口。

设计原则和 app/rag/client.py 一样：**客户端只在这里创建**。
上层（工具、resolver、executor）都从这里拿，不自己 load_kube_config。

为什么要包 asyncio.to_thread：
    kubernetes 的客户端是【同步阻塞】的。在 async 代码里直接调，会卡住
    整个事件循环 —— 一个 K8s 请求慢几秒，所有并发请求全部停住。
    to_thread 把它丢进线程池，事件循环继续跑。

配置来源：
    load_kube_config() 读 ~/.kube/config。
    kind create cluster 会自动写好这个文件，所以不用手工配。
"""

import asyncio
from functools import lru_cache
from datetime import datetime, timezone
from kubernetes import client, config
from datetime import datetime, timedelta, timezone




# ⚠️ 写操作【必须】显式指定 Content-Type，不能靠客户端默认值。
#
#    kubernetes 客户端的 select_header_content_type() 只做一件事：
#    在候选列表里找【第一个名字里含 "json" 的】。而候选列表第一项是
#    'application/json-patch+json'（RFC 6902，body 必须是操作数组），
#    和我们传的 dict 形状完全不符。不指定就会用这个默认值。
#
#    用 merge-patch（RFC 7386）而不是 strategic-merge：
#      · merge-patch 里【数组是整体替换】
#      · strategic-merge 里数组按 name 合并 ——
#        后者删不掉容器里已存在的 env 条目，回滚会"看起来成功但没恢复"
MERGE_PATCH = "application/merge-patch+json"

# ---------- 客户端单例 ----------

_config_loaded = False


def _ensure_config() -> None:
    global _config_loaded
    if not _config_loaded:
        config.load_kube_config()
        _config_loaded = True


@lru_cache(maxsize=1)
def core_api() -> client.CoreV1Api:
    _ensure_config()
    return client.CoreV1Api()

@lru_cache(maxsize=1)
def apps_api() -> client.AppsV1Api:
    _ensure_config()
    return client.AppsV1Api()


# ---------- 同步实现（真正干活的地方）----------

def _pod_summary(pod) -> dict:
    statuses = pod.status.container_statuses or []
    return {
        "name": pod.metadata.name,
        "phase": pod.status.phase,
        "ready": bool(statuses) and all(s.ready for s in statuses),
        "restarts": sum(s.restart_count for s in statuses),
    }


def _list_pods_sync(service: str, namespace: str) -> list[dict]:
    resp = core_api().list_namespaced_pod(
        namespace=namespace,
        label_selector=f"service={service}",
    )
    return [_pod_summary(p) for p in resp.items]


# ---------- 异步门面（上层只调这些）----------

async def list_pods(service: str, namespace: str) -> list[dict]:
    """按逻辑服务名列出 Pod。"""
    return await asyncio.to_thread(_list_pods_sync, service, namespace)


# ---------- 资源名解析：Pod -> ReplicaSet -> Deployment ----------

def _owner_name(obj, kind: str) -> str | None:
    """从 ownerReferences 里找出指定 kind 的拥有者名字。"""
    for ref in (obj.metadata.owner_references or []):
        if ref.kind == kind:
            return ref.name
    return None


def _resolve_deployment_sync(service: str) -> dict | None:
    # 跨所有命名空间找，【不】使用调用方给的 namespace
    resp = core_api().list_pod_for_all_namespaces(
        label_selector=f"service={service}",
    )
    if not resp.items:
        return None

    # 同一个逻辑服务名出现在多个命名空间 —— 无法唯一确定，不猜
    namespaces = {p.metadata.namespace for p in resp.items}
    if len(namespaces) > 1:
        return None

    pod = resp.items[0]
    rs_name = _owner_name(pod, "ReplicaSet")
    if not rs_name:
        return None

    rs = apps_api().read_namespaced_replica_set(rs_name, pod.metadata.namespace)
    deploy_name = _owner_name(rs, "Deployment")
    if not deploy_name:
        return None

    return {
        "namespace": pod.metadata.namespace,
        "deployment": deploy_name,
        "replicaset": rs_name,
        "pod": pod.metadata.name,
    }


async def resolve_deployment(service: str) -> dict | None:
    """逻辑服务名 -> 真实工作负载。走 ownerReferences，跨命名空间查找。"""
    return await asyncio.to_thread(_resolve_deployment_sync, service)


# ---------- 写操作 ----------

def _rollout_restart_sync(namespace: str, deployment: str) -> dict:
    """等价于 kubectl rollout restart deployment/<name>。

    原理：给 Pod 模板打一个带时间戳的 annotation。
          模板变了 -> Deployment 创建新 ReplicaSet -> 滚动重建【全部】副本。
    """
    now = datetime.now(timezone.utc).isoformat()
    apps_api().patch_namespaced_deployment(
        name=deployment,
        namespace=namespace,
        body={"spec": {"template": {"metadata": {"annotations": {
            "kubectl.kubernetes.io/restartedAt": now}}}}},
        _content_type=MERGE_PATCH,
    )
    return {"namespace": namespace, "deployment": deployment, "restarted_at": now}


async def rollout_restart(namespace: str, deployment: str) -> dict:
    """滚动重启一个 Deployment。

    ⚠️ 影响范围是【全部】副本 —— 即使只有 1 个实例异常，另外 2 个也会被重建。
    """
    return await asyncio.to_thread(_rollout_restart_sync, namespace, deployment)


# ---------- 变更记录 ----------

def _parse_window(window: str) -> timedelta:
    """把 "30m" / "2h" / "24h" 解析成 timedelta。"""
    try:
        value, unit = int(window[:-1]), window[-1]
    except (ValueError, IndexError):
        raise ValueError(f"无法解析的时间窗口: {window!r}，应为 30m / 2h / 24h 这类写法")

    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise ValueError(f"不支持的时间单位: {unit!r}")


def _list_recent_changes_sync(service: str, namespace: str, window: str) -> dict:
    span = _parse_window(window)
    now = datetime.now(timezone.utc)
    cutoff = now - span

    resp = apps_api().list_namespaced_replica_set(
        namespace=namespace,
        label_selector=f"service={service}",
    )

    changes = []
    for rs in resp.items:
        created = rs.metadata.creation_timestamp
        if created is None or created < cutoff:
            continue
        containers = rs.spec.template.spec.containers or []
        changes.append({
            "kind": "rollout",
            "replicaset": rs.metadata.name,
            "created_at": created.isoformat(),
            "age_seconds": int((now - created).total_seconds()),
            "images": [c.image for c in containers],
            "desired_replicas": rs.spec.replicas or 0,
            "current_replicas": rs.status.replicas or 0,
            "ready_replicas": rs.status.ready_replicas or 0,
        })

    changes.sort(key=lambda c: c["age_seconds"])
    return {
        "service": service,
        "namespace": namespace,
        "window": window,
        "total": len(changes),
        "changes": changes,
    }


async def list_recent_changes(service: str, namespace: str, window: str) -> dict:
    """最近窗口内的 ReplicaSet 创建记录 = 发布/变更记录。"""
    return await asyncio.to_thread(
        _list_recent_changes_sync, service, namespace, window)



# ---------- 扩缩容 ----------

def _scale_deployment_sync(namespace: str, deployment: str, replicas: int) -> dict:
    apps_api().patch_namespaced_deployment(
        name=deployment,
        namespace=namespace,
        body={"spec": {"replicas": replicas}},
        _content_type=MERGE_PATCH,
    )
    return {"namespace": namespace, "deployment": deployment, "replicas": replicas}


async def scale_deployment(namespace: str, deployment: str, replicas: int) -> dict:
    """改 Deployment 的期望副本数。

    注意：这才是 K8s 里"扩容"的正确做法。
    删/加 Pod 是没用的 —— 控制器会立刻把副本数补回去。
    """
    return await asyncio.to_thread(
        _scale_deployment_sync, namespace, deployment, replicas)


# ---------- 回滚 ----------

def _revision_of(obj) -> int:
    ann = obj.metadata.annotations or {}
    return int(ann.get("deployment.kubernetes.io/revision", "0"))


def _rollback_deployment_sync(namespace: str, deployment: str,
                              revision: str) -> dict:
    """等价于 kubectl rollout undo deployment/<name>。

    原理：K8s 为每次变更保留一个 ReplicaSet，每个 RS 上带
          deployment.kubernetes.io/revision 注解。
          回滚 = 把目标版本的 Pod 模板重新打回 Deployment。
    """
    apps = apps_api()
    d = apps.read_namespaced_deployment(deployment, namespace)
    current = _revision_of(d)

    owned = [
        rs for rs in apps.list_namespaced_replica_set(namespace).items
        if any(r.kind == "Deployment" and r.name == deployment
               for r in (rs.metadata.owner_references or []))
    ]
    owned.sort(key=_revision_of, reverse=True)

    if revision:
        target = next((rs for rs in owned
                       if _revision_of(rs) == int(revision)), None)
    else:
        # 「回滚到上一个稳定版本」≠「revision 减一」。
        # 找 revision 比当前小、且【确实有 Pod 就绪】的最新那个 ——
        # 在"发布卡住、旧版本仍在服务"的场景里，正在服务的那版就是它。
        target = next(
            (rs for rs in owned
             if _revision_of(rs) < current
             and (rs.status.ready_replicas or 0) > 0),
            None,
        )
        # 一个都没有就退回"上一个 revision"，等价于 kubectl rollout undo 的默认行为
        if target is None:
            target = next((rs for rs in owned if _revision_of(rs) < current), None)

    if target is None:
        raise ValueError(
            f"找不到可回滚的目标版本：当前 revision={current}，"
            f"历史 revisions={[_revision_of(rs) for rs in owned]}")

    # ⚠️ 必须用 sanitize_for_serialization，不能用 to_dict()。
    #    to_dict() 给的 key 是 Python 属性名（container_port / host_ip），
    #    而 K8s API 要的是 JSON 字段名（containerPort / hostIP）——
    #    用错了会被服务端拒，报错是含糊的 "does not contain declared merge key"。
    #    sanitize_for_serialization 按 attribute_map 转成正确字段名，并自动跳过 None。
    template = apps.api_client.sanitize_for_serialization(target.spec.template)

    apps.patch_namespaced_deployment(
        name=deployment,
        namespace=namespace,
        body={"spec": {"template": template}},
        _content_type=MERGE_PATCH,
    )

    return {
        "namespace": namespace,
        "deployment": deployment,
        "from_revision": current,
        "to_revision": _revision_of(target),
        "source_replicaset": target.metadata.name,
    }


async def rollback_deployment(namespace: str, deployment: str,
                              revision: str = "") -> dict:
    return await asyncio.to_thread(
        _rollback_deployment_sync, namespace, deployment, revision)



# ---------- 发布状态 ----------

def _rollout_status_sync(namespace: str, deployment: str) -> dict:
    apps = apps_api()
    d = apps.read_namespaced_deployment(deployment, namespace)
    st = d.status
    desired = d.spec.replicas or 0

    owned = [
        rs for rs in apps.list_namespaced_replica_set(namespace).items
        if any(r.kind == "Deployment" and r.name == deployment
               for r in (rs.metadata.owner_references or []))
    ]
    owned.sort(key=_revision_of, reverse=True)
    newest = owned[0] if owned else None

    updated = st.updated_replicas or 0
    ready = st.ready_replicas or 0
    current = st.replicas or 0

    # ⚠️ ready_replicas 是【所有 ReplicaSet 汇总】的数字，不是新版自己的。
    #    单独看它会得出"3/3 就绪、一切正常"的错误结论 —— 必须把新版的就绪数单列出来。
    new_desired = (newest.spec.replicas or 0) if newest else 0
    new_ready = (newest.status.ready_replicas or 0) if newest else 0

    if updated < desired:
        summary = (
            f"发布未完成：只有 {updated}/{desired} 个副本更新到新版；"
            f"新 ReplicaSet 起了 {new_desired} 个、其中 【{new_ready} 个就绪】。"
            f"整体 {current} 个 Pod 里 {ready} 个就绪 —— 服务由旧版本维持"
        )
    else:
        summary = f"发布已完成：{desired} 个副本都是当前版本，{ready} 个就绪"

    return {
        "namespace": namespace,
        "deployment": deployment,
        "desired_replicas": desired,
        "current_replicas": st.replicas or 0,
        "updated_replicas": updated,
        "ready_replicas": ready,
        "available_replicas": st.available_replicas or 0,
        "conditions": [
            {"type": c.type, "status": c.status,
             "reason": c.reason, "message": c.message}
            for c in (st.conditions or [])
        ],
        "newest_replicaset": None if newest is None else {
            "name": newest.metadata.name,
            "revision": _revision_of(newest),
            "desired": newest.spec.replicas or 0,
            "current": newest.status.replicas or 0,
            "ready": newest.status.ready_replicas or 0,
        },
        "summary": summary,
    }


async def rollout_status(namespace: str, deployment: str) -> dict:
    """查询一个 Deployment 的发布状态（等价于 kubectl rollout status）。"""
    return await asyncio.to_thread(_rollout_status_sync, namespace, deployment)