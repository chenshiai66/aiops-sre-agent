"""可执行动作白名单 —— 全项目唯一的「执行权限来源」。

为什么不放在知识库里：
    Qdrant 的 payload 是可以被随时修改的数据，而且检索结果会进 LLM 的上下文。
    如果动作能从数据里来，等于让知识库内容拥有了执行权限。这份写死的清单才是权威。

risk 三档：
    auto       低风险且可逆，可以直接执行
    approval   需要人工审批
    forbidden  禁止执行，只能转人工

参数校验：
    每个动作配一个 Pydantic 模型，它同时负责生成给 LLM 的参数说明和校验参数，
    所以不存在"说明和校验不一致"的可能。
    基类 StrictParams 设了 extra="forbid"，多传一个字段就会被拒。
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

# K8s 资源名：小写字母数字，中间可带连字符，首尾必须是字母数字
K8S_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"


class StrictParams(BaseModel):
    """所有动作参数的基类：禁止未声明的字段"""
    model_config = ConfigDict(extra="forbid")


class NoParams(StrictParams):
    """该动作不需要任何参数"""


class RestartDeploymentParams(StrictParams):
    namespace: str = Field(pattern=K8S_PATTERN, max_length=63,
                           description="命名空间")
    deployment: str = Field(pattern=K8S_PATTERN, max_length=63,
                            description="Deployment 名称")


class ScaleUpParams(StrictParams):
    namespace: str = Field(pattern=K8S_PATTERN, max_length=63,
                           description="命名空间")
    deployment: str = Field(pattern=K8S_PATTERN, max_length=63,
                            description="Deployment 名称")
    replicas: int = Field(ge=1, le=50, description="目标副本数，1~50 的整数")


class RollbackDeploymentParams(StrictParams):
    namespace: str = Field(pattern=K8S_PATTERN, max_length=63,
                           description="命名空间")
    deployment: str = Field(pattern=K8S_PATTERN, max_length=63,
                            description="Deployment 名称")
    revision: str = Field(default="", max_length=32,
                          description="目标版本号；留空表示回滚到最近一个仍然健康的版本")


class DeletePvcParams(StrictParams):
    namespace: str = Field(pattern=K8S_PATTERN, max_length=63,
                           description="命名空间")
    pvc: str = Field(pattern=K8S_PATTERN, max_length=253,
                     description="PVC 名称")


@dataclass(frozen=True)
class Action:
    name: str
    reversible: bool
    risk: str
    description: str
    params_model: type[BaseModel]
    executable: bool = True


ACTIONS: dict[str, Action] = {a.name: a for a in [
    Action(
        name="restart_deployment",
        reversible=True,
        risk="auto",
        description="对一个 Deployment 做滚动重启，用于清除单实例内部的异常状态"
                    "（线程池耗尽、连接泄漏、本地缓存污染）",
        params_model=RestartDeploymentParams,
    ),
    Action(
        name="scale_up",
        reversible=True,
        risk="auto",
        description="扩容副本数，用于流量型压力（CPU 饱和、QPS 上涨）",
        params_model=ScaleUpParams,
    ),
    Action(
        name="rollback_deployment",
        reversible=True,
        risk="approval",
        description="回滚到最近一个仍然健康的版本。会丢失本次发布的功能，必须人工确认",
        params_model=RollbackDeploymentParams,
    ),
    Action(
        name="delete_pvc",
        reversible=False,
        risk="forbidden",
        description="删除持久卷声明，数据不可恢复。系统禁止自动执行",
        params_model=DeletePvcParams,
    ),
    Action(
        name="no_action",
        reversible=True,
        risk="approval",   # 语义就是「转人工」，定成 approval 以便路由到 escalator
        description="不执行任何写操作，只输出诊断结论并转人工。"
                    "信息不足、参考资料互相矛盾、或没有把握时选它",
        params_model=NoParams,
        executable=False,
    ),
]}

RISK_ORDER = {"auto": 0, "approval": 1, "forbidden": 2}


def risk_of(name: str) -> str | None:
    action = ACTIONS.get(name)
    return action.risk if action else None


def stricter(a: str, b: str) -> str:
    """取两个风险等级里更保守的那个"""
    return a if RISK_ORDER.get(a, 99) >= RISK_ORDER.get(b, 99) else b


def params_help(action: Action) -> str:
    """从参数模型生成给 LLM 看的参数说明 —— 说明和校验共用同一个定义"""
    fields = action.params_model.model_fields
    if not fields:
        return "无"
    return "，".join(f"{name}（{info.description}）" for name, info in fields.items())


def validate_params(action_name: str, params: dict) -> tuple[bool, dict, str]:
    """校验并规范化参数。返回 (是否通过, 规范化后的参数, 错误说明)"""
    action = ACTIONS.get(action_name)
    if action is None:
        return False, {}, f"未知动作：{action_name}"

    try:
        parsed = action.params_model(**(params or {}))
    except ValidationError as exc:
        detail = "; ".join(
            f"{'.'.join(str(x) for x in e['loc']) or '<root>'}: {e['msg']}"
            for e in exc.errors()
        )
        return False, {}, detail

    return True, parsed.model_dump(), ""