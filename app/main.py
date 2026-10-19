import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import notify, mcp_client as mcp_client
from app.config import settings
from app.graph.builder import build_graph
from app.pending import PendingIndex

log = logging.getLogger("aiops.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = await build_graph(settings.redis_url)
    app.state.pending = PendingIndex(settings.redis_url)
    await mcp_client.start()      # ← 在 lifespan 任务里建立
    yield
    await mcp_client.close()      # ← 【同一个任务】里关闭


app = FastAPI(lifespan=lifespan)

# ---------- 后台任务 ----------

# ⚠️ 必须持有 Task 的【强引用】。
#    asyncio 对 Task 只保留弱引用，一个没人引用的 Task 可能在执行到一半时
#    被 GC 掉 —— 而且是静默的，你只会发现"图莫名其妙没跑完"。
_running: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _running.add(task)
    task.add_done_callback(_running.discard)




async def _run_graph(fault_id: str, service: str, payload, cfg: dict) -> None:
    """后台跑一张图。payload 要么是初始 state，要么是 Command（批准后继续）。

    ⚠️ 异常必须在这里吃掉 —— HTTP 响应早就发出去了，没人接得住。
       所以出事先写日志（留 traceback）、再发通知（让人知道），
       否则就是"静默失败"。
    """
    try:
        result = await app.state.graph.ainvoke(payload, cfg)

        if result.get("__interrupt__"):
            await app.state.pending.add(fault_id)

    except Exception as exc:
        log.exception("故障处理异常 fault_id=%s", fault_id)
        await notify({"fault_id": fault_id, "service": service},
                     "run_failed", detail=str(exc)[:200])


class FaultIn(BaseModel):
    """字段对齐 Alertmanager 推送的真实形状"""
    alertname: str = "UnknownAlert"
    service: str
    env: str = "prod"
    severity: str = "P3"

    cluster: str | None = None
    namespace: str | None = None
    instance: str | None = None

    metric: str | None = None
    value: float | None = None
    threshold: float | None = None
    duration: str | None = None
    started_at: str | None = None
    labels: dict = Field(default_factory=dict)

class ApprovalIn(BaseModel):
    approved: bool
    by: str = "unknown"
    comment: str = ""


@app.post("/faults", status_code=202)
async def create_fault(body: FaultIn):
    """受理一个故障，【立即返回】，处理在后台跑。

    ⚠️ 为什么不在请求里跑完：
       一次故障包含 3~4 次 LLM 调用，加上 verify 的 30 秒观测窗口，
       总共 30~60 秒。同步跑的话客户端/网关会先超时断开，
       而图还在后台继续跑 —— 调用方以为失败了，实际还在动。

    改成：立即返回 fault_id，用 GET /faults/{fault_id} 轮询进展。
    """
    fault_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": fault_id}}
    initial = {"fault_id": fault_id,
               "raw_alert": body.model_dump(exclude_none=True),
               "audit": []}

    _spawn(_run_graph(fault_id, body.service, initial, cfg))

    return {
        "fault_id": fault_id,
        "status": "accepted",
        "poll": f"GET /faults/{fault_id}",
    }




@app.get("/faults/pending")
async def list_pending_faults():
    """列出当前等待审批的故障。"""
    ids = await app.state.pending.list_all()
    return {"count": len(ids), "awaiting_approval": ids}


@app.get("/notifications")
async def list_notifications(limit: int = 20):
    """最近的通知，最新的在前。"""
    items = await notify.list_recent(limit)
    return {"count": len(items), "notifications": items}




@app.get("/faults/{fault_id}")
async def get_fault(fault_id: str):
    """查一条故障的当前状态 —— 也是 POST /faults 之后的【轮询接口】。

    status 取值：
        running            后台还在跑
        awaiting_approval  停在审批点等人
        finished           跑完了，看 outcome
    """
    cfg = {"configurable": {"thread_id": fault_id}}
    snap = await app.state.graph.aget_state(cfg)

    if not snap.values:
        raise HTTPException(status_code=404, detail=f"没有这个故障：{fault_id}")

    if await app.state.pending.contains(fault_id):
        status = "awaiting_approval"
    elif snap.next:
        status = "running"
    else:
        status = "finished"

    # 审批单（如果这个 LangGraph 版本暴露了 interrupts）
    interrupts = getattr(snap, "interrupts", ()) or ()
    approval_request = interrupts[0].value if interrupts else None

    return {
        "fault_id": fault_id,
        "status": status,
        "next": list(snap.next),
        "outcome": snap.values.get("outcome"),
        "approval_request": approval_request,
        "state": snap.values,
    }



@app.post("/faults/{fault_id}/approve", status_code=202)
async def approve_fault(fault_id: str, body: ApprovalIn):
    cfg = {"configurable": {"thread_id": fault_id}}
    snap = await app.state.graph.aget_state(cfg)

    if not snap.values:
        raise HTTPException(status_code=404, detail=f"没有这个故障：{fault_id}")
    if not snap.next:
        raise HTTPException(status_code=409, detail="该故障已经结束，无法审批")

    # 同样不在请求里跑完：resume 之后还要 executor → verify（30 秒观测）。
    await app.state.pending.remove(fault_id)  # 已经有人批了，先摘掉
    _spawn(_run_graph(fault_id, snap.values.get("service") or "unknown",
                      Command(resume=body.model_dump()), cfg))

    return {
        "fault_id": fault_id,
        "status": "accepted",
        "poll": f"GET /faults/{fault_id}",
    }