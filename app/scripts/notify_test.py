# app/scripts/notify_test.py
"""验证通知：幂等、EVENTS 表过滤、列表可查。"""

import asyncio
import uuid

from app.notify import EVENTS, list_recent, notify

# ⚠️ fault_id 必须每次随机。
#    写死的话，第二次运行脚本时 Redis 里那条 SETNX 键还在，
#    "第一次发送"会被自己的幂等机制挡住 —— 测试自己把自己绊倒。
FAKE = {"fault_id": f"test-notify-{uuid.uuid4().hex[:8]}",
        "service": "demo-service", "severity": "P1"}



async def main():
    # ① 不在表里的 kind 应该被跳过
    r = await notify(FAKE, "rejected")
    print(f"  {'✓' if not r['sent'] else '✗'} 不在 EVENTS 里的 kind 被跳过：{r}")

    # ② 第一次发应该成功
    r1 = await notify(FAKE, "exec_error", detail="第一次")
    print(f"  {'✓' if r1.get('sent') else '✗'} 第一次发送成功：{r1}")

    # ③ 第二次发同一条应该被幂等挡住（模拟 interrupt 重跑）
    r2 = await notify(FAKE, "exec_error", detail="第二次")
    ok = (not r2.get("sent")) and "已经发过" in (r2.get("reason") or "")
    print(f"  {'✓' if ok else '✗'} 第二次被幂等挡住：{r2}")

    # ④ 列表里应该只有一条
    items = await list_recent(10)
    mine = [x for x in items if x["fault_id"] == FAKE["fault_id"]]
    print(f"  {'✓' if len(mine) == 1 else '✗'} 列表里只有 1 条（实际 {len(mine)}）")

    print(f"\nEVENTS 表共 {len(EVENTS)} 种：")
    for k, (lvl, title) in EVENTS.items():
        print(f"  {lvl:8s} {k:20s} {title}")


if __name__ == "__main__":
    asyncio.run(main())