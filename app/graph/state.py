from typing import Annotated, TypedDict
import operator


class FaultState(TypedDict, total=False):
    # ---- 身份：全链路贯穿 ----
    fault_id: str
    raw_alert: dict

    # ---- dispatcher ----
    service: str
    env: str
    severity: str
    namespace: str  # ← 新增：来自告警，是操作目标的必备信息
    instance: str  # ← 新增：来自告警，是操作目标的必备信息
    deployment: str

    # ---- detector ----
    symptoms: str
    root_cause: str
    evidence: list[dict]   # 注意：无 reducer，是覆盖语义。多节点写入前需先加 Annotated[..., operator.add]
    confidence: float
    hypotheses: list[str]
    missing_info: list[str]


    # ---- retriever ----
    retrieved: list[dict]

    # ---- remediator ----
    risk_level: str
    planned_action: dict | None
    exec_result: dict | None
    verify_result: dict | None

    # ---- escalator ----
    escalation: dict | None
    approval: dict | None

    # ---- reviewer ----
    outcome: str
    knowledge_entry: dict | None

    # ---- 全局 ----
    audit: Annotated[list[dict], operator.add]