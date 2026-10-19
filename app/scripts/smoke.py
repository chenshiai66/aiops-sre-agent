"""
冒烟测试
"""


# scripts/smoke.py
import asyncio, uuid
from app.graph.builder import build_graph
from app import k8s, mcp_client as mcp_client
import json


async def main():
    # MCP 会话必须在【本任务】里建立，并在【本任务】里关闭。
    # 见 app/mcp/mcp_client.py 的模块 docstring。
    await mcp_client.start()
    try:
        await _diagnose_once()
    finally:
        await mcp_client.close()


async def _diagnose_once():
    """原来 main() 的全部内容，原样搬过来。"""

    # 从集群里找一个【真的没就绪】的 Pod 当告警目标
    pods = await k8s.list_pods("demo-service", "prod-order")
    target = next((p for p in pods if not p["ready"]), None)
    if target is None:
        print("集群里没有异常 Pod —— 先弄坏一个再跑。两条路，走的是不同的处置路径：\n")
        print("【A】弄坏单个 Pod → 会选 restart_deployment（auto，直接执行）")
        print('     $pod = kubectl -n prod-order get pods -o jsonpath="{.items[0].metadata.name}"')
        print("     kubectl -n prod-order exec $pod -- curl -s -X POST http://127.0.0.1:8000/break\n")
        print("【B】让新版本起不来 → 会选 rollback_deployment（approval，停在审批点）")
        print("     kubectl -n prod-order set env deployment/order-svc START_BROKEN=1")
        print("     （等 40 秒，滚动更新会卡住）")
        return

    graph = await build_graph("redis://localhost:6379/0")
    fault_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": fault_id}}

    initial = {
        "fault_id": fault_id,
        "raw_alert": {
            "alertname": "HighErrorRate",
            "service": "demo-service",
            "env": "prod",
            "severity": "P1",
            "cluster": "prod-sh-01",
            "namespace": "prod-order",
            "instance": target["name"],
            "metric": "ready_instances",
            "value": sum(1 for p in pods if p["ready"]),
            "threshold": len(pods),
            "duration": "5m",
            "started_at": "2025-10-26T18:12:00+08:00",
            "labels": {"team": "trade", "tier": "critical"},
        },
        "audit": [],
    }

    result = await graph.ainvoke(initial, cfg)
    interrupts = result.get("__interrupt__") or []

    # ---- 只有跑到底了才检查不变量 ----
    #      （停在审批点时 outcome 还没产生，断言会误报）
    if not interrupts:
        nodes = [a.get("node") for a in result.get("audit", [])]
        for required in ("dispatcher", "detector", "retriever", "remediator", "reviewer"):
            assert required in nodes, f"{required} 没跑：{nodes}"
        assert result.get("outcome"), "reviewer 没写 outcome —— 检查它是否忘了 return"


    print("fault_id:", fault_id)
    print("outcome :", result.get("outcome"))
    print("audit   :", len(result.get("audit", [])))
    print("symptoms  :", result.get("symptoms"))
    print("root_cause:", result.get("root_cause"))
    print("confidence:", result.get("confidence"))
    print("hypotheses :", result.get("hypotheses"))
    print("missing    :", result.get("missing_info"))

    print("--- 诊断取证 ---")
    for a in result.get("audit", []):
        if a.get("node") == "detector":
            print("rounds_exhausted:", a.get("rounds_exhausted"))
            for t in a.get("tools_used", []):
                print(f"   {t['tool']}({t['args']}) -> {t['preview'][:140]}")

    print("--- 处置 ---")
    pa = result.get("planned_action") or {}
    print("risk_level:", result.get("risk_level"))
    print("action    :", pa.get("name"), pa.get("params"))
    print("analysis  :", pa.get("analysis"))
    print("refs      :", pa.get("referenced_docs"))
    print("invalid   :", pa.get("invalid"))
    print("rejected  :", pa.get("rejected_reason"))

    ex = result.get("exec_result") or {}
    print("exec      :", ex.get("status"), ex.get("params") or ex.get("reason"))

    vr = result.get("verify_result") or {}
    print("verify    :", vr.get("status"),
          f"{vr.get('pods_ready')}/{vr.get('pods_total')} 就绪",
          f"| 等了 {vr.get('waited_seconds')}s（{vr.get('attempts')} 次观测）",
          "|", vr.get("reason") or "")


    # 哪几个节点真的跑了 —— 最有信息量的一行
    print("nodes ran  :", [a.get("node") for a in result.get("audit", [])])

    # 检索到底返回了什么
    hits = result.get("retrieved", [])
    print("retrieved  :", len(hits), "条")
    for h in hits:
        print(f"   [{h['score']:.4f}] {h.get('source')} | {h.get('title')}")



    snap = await graph.aget_state(cfg)
    print("next    :", snap.next)


    # ---- 停在审批点：审批提示放最后 ----
    #      它是"下一步该做什么"，不该挡住"这次跑出了什么"
    if interrupts:
        print("\n=== 停在审批点（需要人工批准）===")
        print(json.dumps(interrupts[0].value, ensure_ascii=False, indent=2))
        print(f"\n批准：POST /faults/{fault_id}/approve")
        print('  body: {"approved": true, "by": "zhang", "comment": "..."}')

if __name__ == "__main__":
    asyncio.run(main())