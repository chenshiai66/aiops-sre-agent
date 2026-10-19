
"""知识库种子数据。

payload 结构必须和 indexer.upsert_documents 一致：
    doc_id / title / source / content / metadata

source 取值：
    "runbook"           运维手册（该怎么做）
    "incident-history"  历史故障案例（以前怎么坏的）

metadata 里省略 service 表示「通用知识」，不绑定具体服务。
"""

DOCS = [
    # ---------- 针对 demo-service 的预案 ----------
    {
        "doc_id": "rb-001",
        "title": "单实例就绪失败（其余副本正常）",
        "source": "runbook",
        "content": (
            "适用场景：单个实例的 readiness probe 失败，其余副本正常，"
            "且【异常实例与正常实例属于同一个 ReplicaSet】。\n"
            "⚠️ 判据：如果异常实例属于【较新的】ReplicaSet、而正常实例都在旧的里，"
            "那不是单实例异常，是【新版本整体失败】—— 走回滚，重启无效。\n"
            "典型根因：该 Pod 内部状态异常，如线程池耗尽、连接泄漏、本地缓存污染。\n"
            "处置：确认是同 RS 内的单实例异常 → rollout restart 该 Deployment → "
            "观察 30 秒就绪数是否恢复 → 未恢复则升级排查。\n"
            "风险：中。rollout restart 会【滚动重建全部副本】，不只是坏的那一个 —— "
            "其余副本会依次被替换，期间可用副本数短暂下降。"
        ),
        "metadata": {"service": "demo-service", "category": "instance",
                     "severity": "high", "confidence": 0.8},
    },
    {
        "doc_id": "rb-002",
        "title": "下游依赖超时导致上游 5xx",
        "source": "runbook",
        "content": (
            "适用场景：服务 5xx 上升，同时下游依赖的延迟或错误率同步上升。\n"
            "典型根因：下游服务故障或网络抖动，上游未做降级。\n"
            "处置：确认下游是否同期异常 → 检查熔断降级配置 → "
            "不要重启上游，重启无法解决依赖问题。\n"
            "风险：高。上游无法自愈，需协调下游团队。升级路径：转人工。"
        ),
        "metadata": {"service": "demo-service", "category": "dependency",
                     "severity": "critical", "confidence": 0.85},
    },
    {
        "doc_id": "rb-003",
        "title": "实例 CPU 饱和导致响应变慢",
        "source": "runbook",
        "content": (
            "适用场景：实例 CPU 使用率持续高于 80%，延迟上升但错误率未明显波动。\n"
            "典型根因：流量增长或单实例热点。\n"
            "处置：确认是流量型而非故障型 → 扩容副本数 +2 → 观察 CPU 是否回落。\n"
            "风险：低。扩容可逆，回滚即缩容。"
        ),
        "metadata": {"service": "demo-service", "category": "capacity",
                     "severity": "medium", "confidence": 0.75},
    },

    # ---------- 通用手册（不绑定服务）----------
    {
        "doc_id": "rb-generic-5xx",
        "title": "运维手册：服务不可用（5xx / 503）标准处置流程",
        "source": "runbook",
        "content": (
            "适用范围：服务错误率上升、返回 503/502、健康检查失败。\n"
            "处置步骤：1）确认影响范围，统计受影响服务与上游调用方；"
            "2）检查最近 30 分钟的发布与配置变更记录，优先怀疑变更引入；"
            "3）查看 Pod 状态与重启次数，判断是否 CrashLoopBackOff；"
            "4）检查实例资源使用率（CPU / memory）与就绪探针；"
            "5）对比下游依赖的错误率与延迟，判断是自身故障还是依赖故障。\n"
            "风险：以上全部为只读诊断，无副作用。"
        ),
        "metadata": {"category": "diagnosis", "severity": "critical"},
    },
    {
        "doc_id": "rb-generic-rollback",
        "title": "运维手册：变更后故障快速回滚指引",
        "source": "runbook",
        "content": (
            "适用场景：故障发生时间与最近一次发布/配置变更高度吻合，"
            "且新版本的实例【始终无法就绪】。\n"
            "处置：1）确认变更时间与故障起始时间的先后关系；"
            "2）回滚到最近一个仍然健康的版本；"
            "3）观察 30 秒就绪数是否恢复；"
            "4）保留现场：记录变更内容与回滚前后的指标对比。\n"
            "风险：中。会丢失本次变更的功能，必须人工确认。"
            "⚠️ 【不幂等】：如果已经没有可回退的健康版本，回滚会直接失败报错。"
        ),
        "metadata": {"category": "change", "severity": "high"},
    },

    # ---------- 历史故障案例 ----------
    {
        "doc_id": "inc-ebabd0a1d5",
        "title": "故障复盘：demo-service Pod CrashLoopBackOff",
        "source": "incident-history",
        "content": (
            "【现象】Pod 反复重启，5xx 比例短时冲高后随副本剔除回落。\n"
            "【根因】数据库连接池耗尽，应用启动时初始化连接失败后退出，"
            "被 kubelet 反复拉起。\n"
            "【当时处置】确认连接池配置在上次发布中被改小，回滚该发布版本后恢复。\n"
            "【经验】CrashLoopBackOff 且故障时间与变更吻合时，优先回滚而不是重启。"
        ),
        "metadata": {"service": "demo-service", "category": "change",
                     "severity": "critical", "confidence": 0.72,
                     "root_cause": "连接池配置被改小"},
    },


    {
        "doc_id": "rb-decoy-payment",
        "title": "payment-svc 连接池耗尽的处置",
        "source": "runbook",
        "content": (
            "适用场景：payment-svc 出现数据库连接超时，5xx 比例上升。\n"
            "处置：扩容连接池上限 → 重启 payment-svc → 观察连接数回落。\n"
            "注意：本手册仅适用于 payment-svc。"
        ),
        "metadata": {"service": "payment-svc", "category": "instance",
                     "severity": "high"},
    },

    {
        "doc_id": "rb-decoy-irrelevant",
        "title": "运维手册：办公网 VPN 客户端安装指引",
        "source": "runbook",
        "content": "适用场景：员工笔记本无法连接公司内网。"
                   "处置：下载客户端 → 导入配置 → 重启网络服务。",
        "metadata": {"category": "other", "severity": "low"},
    },

]