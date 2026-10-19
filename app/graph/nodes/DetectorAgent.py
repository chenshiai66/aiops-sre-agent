"""
故障定位 Agent｜先用只读工具取证，再输出诊断结论。

⚠️ 工具循环在【节点内部】，整个循环算一个 super-step。
   调用明细写进 state["audit"]，保证可追溯。
   需要中途中断/审批时，再把它展开成子图。
"""

import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.graph.schemas import DiagnosisOut
from app.graph.state import FaultState
from app.llm import get_llm
from app.mcp_client import get_tools

MAX_TOOL_ROUNDS = 5

SYSTEM = """你是资深 SRE，负责根据告警信息做故障定位。

你可以调用只读工具获取信息。规则：
- 先查证再下结论。凡是工具能拿到的事实，不要靠猜
- 工具都是只读的，可以放心调用
- 同一个工具不要用相同参数重复调用
- 只能使用已提供的工具，不要臆造工具名
- 最多几轮就要收敛，不要无限查下去
- 只根据你实际掌握的信息推理，不要编造指标或日志
- symptoms 只写现象，hypotheses 只写候选根因，两者都不要混入分析过程
- 没有确凿证据时，root_cause 就写「待确认」，把分析放到 hypotheses 里
- confidence 是对 root_cause 的把握。root_cause 待确认时，confidence 不得高于 0.4"""


def _alert_prompt(state: FaultState) -> str:
    return f"""请分析以下故障告警：

<alert>
服务: {state.get("service", "unknown")}
环境: {state.get("env", "unknown")}
严重度: {state.get("severity", "unknown")}
原始告警: {state.get("raw_alert", {})}
</alert>"""


def _tool_text(result) -> str:
    """把工具返回值统一成文本。

    ⚠️ 两种包装返回两种形状：
        · 本地 @tool（本项目已不再用）  -> 字符串
        · MCP 工具                      -> 内容块列表
          [{'type': 'text', 'text': '{"namespace": ...}', 'id': 'lc_...'}]

        MCP 协议的工具返回本来就是【内容块数组】（可以混文本 / 图片 / 资源引用），
        langchain-mcp-adapters 原样带过来，没有做扁平化。
        不在这里抹平，ToolMessage 和 audit 里就会出现两种形状。
    """
    if isinstance(result, str):
        return result

    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)

    return json.dumps(result, ensure_ascii=False, default=str)


async def _run_tool(tool_call: dict, tools_by_name: dict) -> str:
    """执行一次工具调用。任何失败都转成文本回给模型，不让它拖垮整张图。"""
    name = tool_call.get("name")
    args = tool_call.get("args") or {}

    tool = tools_by_name.get(name)
    if tool is None:
        return f"错误：不存在名为 {name} 的工具。请只使用已提供的工具。"

    try:
        result = await tool.ainvoke(args)
    except Exception as exc:
        return f"工具 {name} 执行失败：{exc}"

    return _tool_text(result)


# 单个工具结果拼进 prompt 时的长度上限。
# ! 为什么必须有：get_pod_status / list_recent_changes 在大集群上会返回很长的
#    JSON（几十个 Pod × 每条七八个字段）。不截断的话：
#      · prompt 可能爆掉——超出模型上下文直接报错
#      · 真正关键的那几行会被淹没在噪音里
#    而 audit 里本来就只留 200 字，两边口径也不一致。
TOOL_RESULT_LIMIT = 3000


def _tools_transcript(runs: list[dict]) -> str:
    if not runs:
        return "（没有调用任何工具）"

    blocks = []
    for r in runs:
        text = r["result"]
        if len(text) > TOOL_RESULT_LIMIT:
            text = (text[:TOOL_RESULT_LIMIT]
                    + f"\n…（结果过长已截断，原始长度 {len(r['result'])} 字符）")
        blocks.append(
            f"### {r['tool']}({json.dumps(r['args'], ensure_ascii=False)})\n{text}")
    return "\n\n".join(blocks)


async def detector_node(state: FaultState) -> dict:
    # 工具来自 MCP server。会话由入口（lifespan / smoke）用 start() 建好，
    # 这里只是取一下 —— 所以是同步的。
    tools = get_tools()
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = get_llm().bind_tools(tools)

    messages = [
        SystemMessage(content=SYSTEM),
        HumanMessage(content=_alert_prompt(state)),
    ]
    runs: list[dict] = []
    rounds_exhausted = True

    for _ in range(MAX_TOOL_ROUNDS):
        ai = await llm_with_tools.ainvoke(messages)
        messages.append(ai)

        if not ai.tool_calls:
            rounds_exhausted = False
            break

        for tc in ai.tool_calls:
            result = await _run_tool(tc, tools_by_name)
            runs.append({"tool": tc.get("name"), "args": tc.get("args"),
                         "result": result})
            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    # ---- 结构化输出：把工具结果渲染成纯文本再喂，
    #      避免把带 tool_calls 的消息交给未绑定工具的模型（厂商兼容性不一致）----
    structured = get_llm().with_structured_output(DiagnosisOut)
    out = await structured.ainvoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            _alert_prompt(state)
            + "\n\n## 工具查询结果\n\n"
            + _tools_transcript(runs)
            + "\n\n现在基于以上全部信息，给出最终的诊断结论。"
        )),
    ])

    return {
        "symptoms":     out.symptoms,
        "hypotheses":   out.hypotheses,
        "root_cause":   out.root_cause,
        "confidence":   out.confidence,
        "missing_info": out.missing_info,
        "evidence": [
            {"source": "llm", "hypotheses": out.hypotheses,
             "confidence": out.confidence},
            {"source": "tools", "calls": [r["tool"] for r in runs]},
        ],
        "audit": [{
            "node": "detector",
            "action": "diagnosed",
            "confidence": out.confidence,
            "hypotheses_count": len(out.hypotheses),
            "rounds_exhausted": rounds_exhausted,
            "tools_used": [
                {"tool": r["tool"], "args": r["args"], "preview": r["result"][:200]}
                for r in runs
            ],
        }],
    }