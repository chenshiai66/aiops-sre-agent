"""通知层 —— 把「该让人知道的事」推出去。

现在整个系统是【全拉取式】的：不主动 GET /faults/{id} 就什么都不知道。
而 escalation / 执行失败这些路径如果不通知，等于白加 —— 没人会去查。

⚠️ 三条约束：

① 绝不抛异常
   通知失败不能影响故障处置。通道的错误全部吃掉，只记进返回值。

② 「什么值得通知」只判断一遍 —— 就是下面的 EVENTS 表。
   和结局判定（app/graph/outcome.py）一个道理：
   散落到各节点里就会不一致，这个项目已经栽过两次。

③ 同一条通知只发一次（幂等）
   escalator 里 interrupt() 恢复时【节点会从头重跑】，
   放在 interrupt() 之前的副作用会被执行两遍。
   所以用 Redis 的 SETNX 做去重键：notify:{fault_id}:{kind}
"""

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache

import redis.asyncio as aioredis

from app.config import settings

log = logging.getLogger("aiops.notify")

# ⚠️ 这个模块的职责就是"让人看见"，所以不能依赖宿主应用的 logging 配置。
#    Python 根 logger 默认级别是 WARNING，也没有 handler：
#      · log.warning 靠 lastResort 还能打到 stderr（但没有级别前缀）
#      · log.info  会被级别过滤掉，【静默消失】
#    uvicorn 的 logging 配置里没有 root 这一项，管不到我们。
#
#    这个坑真踩过：通知发出去了、Redis 里也有，但 uvicorn 窗口里一个字都没有。
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

NOTIFY_KEY = "faults:notifications"
NOTIFY_MAX = 500          # 列表长度上限，防止无限增长

# kind -> (level, 标题)
#
# ⚠️ 这就是"什么值得通知"的【唯一一份】定义。
#    不在表里的 kind，notify() 直接跳过 —— 这比在每个调用点判断可靠。
#
#    ⚠️ 没有 execution_failed / remediation_failed ——
#       那两种情况会被 reviewer 的终态通知（exec_error / failed）覆盖，
#       在这里再发一条就是同一件事发两遍。
EVENTS = {
    # ---- escalator：需要人做点什么 ----
    "approval_required": ("warning", "需要人工审批"),

    # ---- 来自 API 层：后台任务整个崩了 ----
    "run_failed": ("critical", "故障处理进程异常退出"),


    # ---- reviewer：这次故障最后怎么了 ----
    "exec_error":        ("critical", "执行失败：动了手但没成功"),
    "failed":            ("warning",  "处置后故障未恢复"),
    "resolved":          ("info",     "已自动恢复"),
    "escalated":         ("warning",  "系统未动手，转人工"),
}


@lru_cache(maxsize=1)
def _redis():
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def notify(state: dict, kind: str, detail: str = "") -> dict:
    """发一条通知。返回描述结果的 dict（会进 audit）。

    幂等：同一个 (fault_id, kind) 只会真正发一次。
    绝不抛异常。
    """
    spec = EVENTS.get(kind)
    if spec is None:
        return {"sent": False, "kind": kind, "reason": "不在 EVENTS 表里"}

    fault_id = state.get("fault_id") or "unknown"
    level, title = spec

    try:
        r = _redis()

        # ③ 幂等：SETNX 成功才继续（interrupt 重跑时这里会挡住第二次）
        #    这个键加过期时间 —— 它只需要活过"interrupt 重跑"那几秒，
        #    但也不能设太短：人可能几小时后才批准，那时 reviewer 才发终态通知，
        #    键若已过期就可能重复发。7 天足够，而且不会让 Redis 无限增长。
        first = await r.set(f"notify:{fault_id}:{kind}", "1",
                            nx=True, ex=7 * 24 * 3600)
        if not first:
            return {"sent": False, "kind": kind, "reason": "同一条已经发过了"}

        item = {
            "at": datetime.now(timezone.utc).isoformat(),
            "fault_id": fault_id,
            "kind": kind,
            "level": level,
            "title": title,
            "service": state.get("service"),
            "severity": state.get("severity"),
            "detail": detail or "",
        }

        await r.lpush(NOTIFY_KEY, json.dumps(item, ensure_ascii=False))
        await r.ltrim(NOTIFY_KEY, 0, NOTIFY_MAX - 1)
        # 同时打进日志 —— 值班人在 uvicorn 窗口里能立刻看到。
        # ⚠️ 用【日志级别本身】表达严重度，不要在消息里再手拼 [LEVEL]：
        #    formatter 已经会打 %(levelname)s，手拼一次就成了
        #    "[WARNING] [CRITICAL] ..." —— 两个前缀说的级别还不一样。
        emit = {"info": log.info,
                "warning": log.warning,
                "critical": log.critical}.get(level, log.warning)
        emit("%s | fault=%s service=%s | %s",
             title, fault_id, state.get("service"), detail)

        return {"sent": True, "kind": kind, "level": level}
    except Exception as exc:
        # ① 绝不抛 —— 通知失败不能影响故障处置
        return {"sent": False, "kind": kind, "reason": f"通知失败：{exc}"}


async def list_recent(limit: int = 20) -> list[dict]:
    """最近的通知，最新的在前。"""
    raw = await _redis().lrange(NOTIFY_KEY, 0, limit - 1)
    return [json.loads(x) for x in raw]