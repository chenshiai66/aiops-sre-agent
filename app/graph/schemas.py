from typing import Any, Literal
from pydantic import BaseModel, Field
class DiagnosisOut(BaseModel):
    """detector 的判断结果"""

    symptoms: str = Field(
        description="观察到的现象，只陈述事实：指标、数值、持续时间、影响范围。"
                    "不要包含任何原因推测"
    )
    hypotheses: list[str] = Field(
        description="候选根因，按可能性从高到低排序，每条不超过 20 字。至少给 1 条"
    )
    root_cause: str = Field(
        description="有明确证据支持的根因，一个短短语。"
                    "证据不足时固定填「待确认」，不要在这里展开分析"
    )
    confidence: float = Field(
        ge=0, le=1,
        description="对 root_cause 这一个结论的置信度。"
                    "若 root_cause 为「待确认」，该值必须 ≤ 0.4"
    )
    missing_info: list[str] = Field(
        description="确认根因还需要查什么，具体到可以直接执行的查询"
    )

class RemediationOut(BaseModel):
    """remediator 的处置决定"""

    analysis: str = Field(
        description="为什么选这个动作，一到两句话。要指明依据哪几条参考资料，"
                    "以及为什么排除了其他可能"
    )
    planned_action: str = Field(
        description="从给定的动作清单里【原样】选一个动作名，不要改写、不要自创"
    )
    action_params: dict[str, Any] = Field(
        default_factory=dict,
        description="该动作需要的参数，按清单里这个动作的 params 说明填写"
    )
    suggested_risk: Literal["auto", "approval", "forbidden"] = Field(
        description="你建议的风险等级。注意：这只是建议，最终等级由系统按动作清单判定"
    )
    confidence: float = Field(
        ge=0, le=1,
        description="对本次处置判断的把握。参考冲突或信息不足时应该给低分"
    )
    referenced_docs: list[str] = Field(
        default_factory=list,
        description="你参考了哪些文档，填它们的 doc_id"
    )