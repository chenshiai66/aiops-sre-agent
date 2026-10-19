# app/scripts/executor_test.py
"""执行器【闸门】的边界测试。

⚠️ 这个测试【不碰集群】—— 它只调 resolve_and_check()，
   那个函数是只读的（解析资源 + 比对意图），不会执行任何写操作。

   想验证"真的执行了"，请跑完整流程（smoke 或 POST /faults）——
   不要把它塞回单元测试里。一个每次运行都会改生产状态的测试，
   是不可能被放心重跑的。
"""

import asyncio

from app.remediation.executor import resolve_and_check

# (说明, 动作名, 参数, 服务名, 期望)
#   期望 None   → 应该放行
#   期望 字符串 → 应该拒绝，且拒绝原因里要包含这个词
CASES = [
    ("资源名一致 → 放行（但不执行）",
     "restart_deployment",
     {"namespace": "prod-order", "deployment": "order-svc"},
     "demo-service", None),

    ("★ 资源名不一致 → 拒绝（上一轮发现的矛盾）",
     "restart_deployment",
     {"namespace": "prod-order", "deployment": "demo-service"},
     "demo-service", "资源名不一致"),

    ("命名空间不一致 → 拒绝",
     "restart_deployment",
     {"namespace": "prod-payment", "deployment": "order-svc"},
     "demo-service", "命名空间不一致"),

    ("服务名解析不出来 → 拒绝",
     "restart_deployment",
     {"namespace": "prod-order", "deployment": "order-svc"},
     "unknown-service", "无法解析"),

    ("forbidden 动作 → 兜底拦下",
     "delete_pvc",
     {"namespace": "prod-order", "pvc": "data-pvc"},
     "demo-service", "禁止执行"),

    ("未知动作 → 拒绝",
     "cleanup_connections", {}, "demo-service", "未知动作"),
]


async def main():
    passed = 0
    for desc, name, params, service, expect in CASES:
        real_params, rejection = await resolve_and_check(name, params, service)

        if expect is None:
            hit = rejection is None
            detail = f"放行；注入后的参数 = {real_params}"
        else:
            reason = (rejection or {}).get("reason") or "（竟然放行了！）"
            hit = rejection is not None and expect in reason
            detail = f"拒绝：{reason}"

        passed += hit
        print(f"{'OK ' if hit else '!!!'} [{desc}]")
        print(f"      {name} {params}  service={service!r}")
        print(f"      -> {detail}")

    print(f"\n{passed}/{len(CASES)} 条符合预期")
    print("（本测试只读 —— 没有对集群做任何写操作）")


if __name__ == "__main__":
    asyncio.run(main())
