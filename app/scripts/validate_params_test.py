# app/scripts/validate_params_test.py
"""参数校验的边界测试。

安全机制不能靠"跑正常流程看它没出事"来验证——
必须故意喂坏输入，看它是不是真的挡住了。
"""

from app.remediation.actions import validate_params

# (说明, 动作名, 参数, 期望是否通过)
CASES = [
    ("no_action 被塞了两个参数 —— extra=forbid 应该拦住",
     "no_action", {"namespace": "prod-order", "deployment": "order-svc"}, False),
    ("no_action 正确用法",
     "no_action", {}, True),
    ("漏填 deployment",
     "restart_deployment", {"namespace": "prod-order"}, False),
    ("完全正确",
     "restart_deployment",
     {"namespace": "prod-order", "deployment": "order-svc"}, True),
    ("资源名非法（大写 + 空格）",
     "restart_deployment",
     {"namespace": "prod-order", "deployment": "Order Svc"}, False),
    ("扩容量传了中文",
     "scale_up", {"namespace": "prod-order", "deployment": "order-svc",
                  "replicas": "很多"}, False),
    ("扩容量越界",
     "scale_up", {"namespace": "prod-order", "deployment": "order-svc",
                  "replicas": -5}, False),
    ("扩容量正确",
     "scale_up", {"namespace": "prod-order", "deployment": "order-svc",
                  "replicas": 4}, True),
    ("未知动作",
     "cleanup_connections", {}, False),
    ("forbidden 动作参数合法 → 参数层放行",
     "delete_pvc", {"namespace": "prod-order", "pvc": "data-pvc"}, True),
]


def main():
    passed = 0
    for desc, name, params, expect_ok in CASES:
        ok, normalized, err = validate_params(name, params)
        hit = (ok == expect_ok)
        passed += hit
        print(f"{'OK ' if hit else '!!!'} [{desc}]")
        print(f"      {name} {params}")
        if ok:
            print(f"      -> 通过，规范化后：{normalized}")
        else:
            print(f"      -> 拒绝：{err}")

    print(f"\n{passed}/{len(CASES)} 条符合预期")


if __name__ == "__main__":
    main()