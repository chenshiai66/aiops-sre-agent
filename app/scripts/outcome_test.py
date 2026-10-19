# app/scripts/outcome_test.py
"""exec_blocked 的真值表 —— 纯逻辑，不碰集群。"""

from app.graph.outcome import exec_blocked
from app.graph.outcome import compute_outcome

CASES = [
    # (说明, state, 期望)
    ("没执行过", {}, False),
    ("自动路径，闸门拦下（没人等着）",
     {"exec_result": {"status": "rejected"}}, False),
    ("自动路径，执行抛异常",
     {"exec_result": {"status": "error"}}, True),
    ("人工批准，但闸门拦下",
     {"exec_result": {"status": "rejected"},
      "approval": {"approved": True}}, True),
    ("人工否决（executor 没跑）",
     {"approval": {"approved": False}}, False),
    ("执行成功",
     {"exec_result": {"status": "executed"}}, False),
]


ok = 0
for desc, state, expect in CASES:
    got = exec_blocked(state)
    flag = "✓" if got == expect else "✗"
    if got == expect:
        ok += 1
    print(f" {flag} {desc:28s} → {got}（期望 {expect}）")

print(f"\n{ok}/{len(CASES)} 条符合预期")


print("\n--- compute_outcome 的分支顺序 ---")

OUTCOME_CASES = [
    ("人否决 → rejected",
     {"approval": {"approved": False}, "exec_result": {"status": "rejected"}},
     "rejected"),
    ("人批准+执行抛异常 → exec_error",
     {"approval": {"approved": True}, "exec_result": {"status": "error"}},
     "exec_error"),
    ("人批准+闸门拦下 → exec_error",
     {"approval": {"approved": True}, "exec_result": {"status": "rejected"}},
     "exec_error"),
    ("自动路径+闸门拦下 → rejected",
     {"exec_result": {"status": "rejected"}},
     "rejected"),
    ("remediator 就拒了 → rejected",
     {"planned_action": {"rejected_reason": "参数校验失败：xxx"}},
     "rejected"),
    ("执行成功+验证通过 → resolved",
     {"exec_result": {"status": "executed"},
      "verify_result": {"status": "recovered"}},
     "resolved"),
    ("执行成功+验证失败 → failed",
     {"exec_result": {"status": "executed"},
      "verify_result": {"status": "not_recovered"}},
     "failed"),
    ("执行了但没验证 → unverified",
     {"exec_result": {"status": "executed"},
      "verify_result": {"status": "skipped"}},
     "unverified"),
    ("转人工没动手 → escalated",
     {"escalation": {"reason": "no_knowledge_hit"}},
     "escalated"),
    ("什么都没发生 → noop", {}, "noop"),
]

ok2 = 0
for desc, state, expect in OUTCOME_CASES:
    got = compute_outcome(state)
    flag = "✓" if got == expect else "✗"
    if got == expect:
        ok2 += 1
    print(f" {flag} {desc:34s} → {got}（期望 {expect}）")

print(f"\n{ok2}/{len(OUTCOME_CASES)} 条符合预期")

