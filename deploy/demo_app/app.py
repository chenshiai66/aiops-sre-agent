"""演示用的业务服务。

存在的唯一理由：给 Agent 一个【真实的、可观察的、重启能修好】的故障目标。

故障状态存在【内存】里，所以容器被重建后它自然消失 ——
这就是"重启能修好"的物理原因，不是模拟。
"""

import os
import time

from fastapi import FastAPI, Response

app = FastAPI()

# ★ START_BROKEN=1 时，进程一启动就是坏的。
#   这模拟的是「配置改错导致的启动失败」——重启没用，只有回滚能修。
_broken = os.getenv("START_BROKEN", "").lower() in ("1", "true", "yes")
_started_at = time.time()


@app.get("/health")
def health(response: Response):
    """就绪探针打这个端点。故障时返回 503。"""
    if _broken:
        response.status_code = 503
        return {"status": "broken", "reason": "内部状态异常"}
    return {
        "status": "ok",
        "uptime": round(time.time() - _started_at, 1),
        "instance": os.getenv("HOSTNAME", "unknown"),
    }


@app.post("/break")
def break_me():
    """把自己弄坏 —— 模拟「单实例内部状态异常」，只有重建能修。"""
    global _broken
    _broken = True
    return {"status": "broken"}


@app.get("/")
def root(response: Response):
    """业务端点：故障时返回 500。"""
    if _broken:
        response.status_code = 500
        return {"error": "internal"}
    return {"ok": True}