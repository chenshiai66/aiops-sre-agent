# .resume/rebuild_resume.py
"""把 AIOps 项目加进简历，同时压缩到一页。

做法：**直接在 XML 层操作**，不重建文档 ——
照片、表格样式、页边距、字体全部原样保留。

  · 要保留的段落   -> 原封不动
  · 要改文字的段落 -> 保留 <w:pPr>，只把 run 换掉
  · 要删的段落     -> 摘掉整个 <w:p>
  · 新增的段落     -> 深拷贝一个模板段落再换文字（继承它的间距设置）

段落编号和 resume_dump.py 的 [Pxxx] 一致。

用法：
    <python> rebuild_resume.py <输入.docx> <输出.docx>
"""

import sys
from copy import deepcopy
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.text.paragraph import Paragraph


# ============================ 内容 ============================

# 改文字（键 = 原始段落编号；值是 str 或 [(文字, 是否加粗), ...]）
REWRITE = {
    # 求职意向：Python 提到 Java 前面，顺手统一大小写
    2: "求职意向：【AI 应用开发 / 大模型应用开发 / Python 后端开发】",

    4: "主修课程：Python 92、操作系统 91、面向对象程序设计 91、"
       "计算机系统基础 86.4、数据库概论 83.7",

    8: "· 大模型应用开发：熟悉 LangChain / LangGraph（图编排、状态管理、"
       "checkpoint 持久化）、RAG 检索增强、MCP 协议与 Agent 开发"
       "（ReAct 工具循环、结构化输出）、提示词工程（角色设定、Few-shot、"
       "输出格式约束）及 Coze / Dify 平台。",

    # ★ Python 提前：主语言是 Python，Java 只留一句弱表述
    10: "· 编程语言：以 Python 为主，掌握面向对象编程思想与常用数据结构、算法；"
        "熟悉 Java 基础语法。",

    # ★ 去掉 JavaWeb / Spring —— 不熟的东西写上去就是给面试官递刀子
    11: "· 后端开发：熟悉 Python 后端开发，掌握 FastAPI 接口开发"
        "（中间件、依赖注入、SSE 流式响应）。",

    # 补回来：Qdrant + ES 是两个项目的核心，写进技能里合理
    14: "· 检索与向量化：熟悉 Qdrant 向量检索与 Elasticsearch 全文检索，"
        '掌握"语义 + 关键词"双路召回与元数据过滤。',

    # 标题后面挂上仓库链接：标题加粗，链接常规
    17: [("数据查询智能体", True),
         ("　　https://gitee.com/chen-shie/data-agent", False)],

    # 原 P19「代码仓库」这一格改成「项目简介」（链接已经挪到标题行）
    19: "· 项目简介：面向业务人员的智能取数系统。自然语言问题 → "
        "自动生成可执行 SQL → 查询数仓返回结果，降低数据分析门槛，"
        "支持分组统计、TOP N 等复杂查询。",

    20: "· 架构设计：构建 MySQL（全量元数据）+ Qdrant（向量索引）+ "
        "Elasticsearch（全文索引）三层元数据知识库；向量语义检索与"
        "全文关键词检索并行多路召回表 / 字段 / 指标，作为限定上下文"
        "交由大模型生成 SQL，解决直接调用大模型 SQL 不准、"
        "全量上下文超限的问题。",

    # 原 P22「智能体开发」，把 P23 数据同步 / P24 接口联调并进来
    22: "· 智能体开发：基于 LangGraph 编排「关键词扩展 → 三路召回 → "
        "合并去重与主外键补齐 → LLM 过滤 → 上下文补充 → SQL 生成 → "
        "EXPLAIN 校验 → 错误校正 → 执行」完整链路；并开发元数据同步脚本"
        "（全量 / 增量）与 FastAPI 流式接口（SSE + request_id 日志链路追踪）。",
}

# 整段删掉
DELETE = [
    5,    # 实习经历（标题）—— 只有公司名、没有内容，
    6,    # 科大讯飞那一行     写了反而招来一个答不实的追问
    9,    # 提示词工程 —— 已并入 P8
    12,   # 前端开发
    21,   # 架构设计（内容已被搬到 P20，这一段成了重复）
    23,   # 数据同步 —— 已并入 P22
    24,   # 接口与联调 —— 已并入 P22
]

# 在某个段落【之前】插入整块内容
# 第三个元素是模板：title 用 P17 的样式（带 before=20），bullet 用 P20 的样式
INSERT_BEFORE = {
    17: [
        ("智能运维故障处置 Agent（K8s / AIOps）", True, "title"),

        ("· 技术栈：Python · LangGraph · LangChain · MCP · FastAPI · "
         "Qdrant · Redis · Kubernetes", False, "bullet"),

        ("· 项目简介：生产 K8s 环境的故障自动处置 Agent，自动完成"
         "「取证诊断 → 检索运维手册 → 选动作 → 执行 → 观测验证 → 复盘回写」，"
         "全链路可中断、可恢复、可审计。", False, "bullet"),

        ("· 安全设计：执行前设四道闸门 —— 动作白名单、参数强校验、"
         "资源名从 ownerReferences 解析后与模型意图比对、风险等级取严"
         "（代码可否决模型）；高风险动作经 interrupt() 暂停等人工审批。",
         False, "bullet"),

        ("· 关键难点：把「验证」独立成节点、真轮询集群确认，"
         "借此发现过「patch 返回成功但集群未变」的缺陷；"
         "状态经 Redis checkpoint 持久化，跨进程可恢复。", False, "bullet"),

        ("· 可观测性：每个节点向 audit 追加一条记录，处置完可完整回放；"
         "通知按事件表去重，同一故障最多两条。", False, "bullet"),

        ("· 效果：接口异步化后响应 40~60 秒 → 0.05 秒；"
         "MCP 会话常驻使工具调用 1.3 秒 → 0.016 秒；"
         "处置结论自动回写知识库形成可复用复盘。", False, "bullet"),
    ],
}

# 自我评价：删到只剩前 N 条，并把前两条改写
EVAL_KEEP = 2
EVAL_TEXT = [
    "· 学习与落地：系统学习大模型应用开发技术栈"
    "（LangChain / LangGraph / RAG / MCP / Agent），"
    "能快速上手新技术并独立落地完整项目。",
    "· 基础扎实：软件工程专业系统训练，具备 Python / Java 开发、"
    "数据库、操作系统与软件工程全流程知识，注重代码质量与工程规范。",
]


# ============================ 工具 ============================

def _rpr(bold: bool) -> str:
    """正文 run 的属性。

    ⚠️ 原文里正文 run 只设 color / sz / szCs，字体走文档默认 —— 照抄它，
       中文的 eastAsia 字体才不会跑偏。
    """
    head = '<w:rFonts w:eastAsia="黑体" w:hint="eastAsia"/><w:b/>' if bold else ""
    return (f"<w:rPr>{head}"
            '<w:color w:val="000000"/><w:sz w:val="20"/><w:szCs w:val="20"/>'
            "</w:rPr>")


def make_run(text: str, bold: bool):
    return parse_xml(
        f'<w:r {nsdecls("w")}>{_rpr(bold)}'
        f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
    )


def set_runs(p_el, pieces):
    """把段落正文换成 pieces，保留 <w:pPr>（间距/边框/对齐都在这）。"""
    for child in list(p_el):
        if child.tag != qn("w:pPr"):
            p_el.remove(child)
    for text, bold in pieces:
        p_el.append(make_run(text, bold))


def main(src: str, dst: str):
    doc = Document(src)
    body = doc.element.body

    # 收集正文里的段落元素；编号和 resume_dump.py 的 [Pxxx] 一致
    paras = [c for c in body.iterchildren() if c.tag == qn("w:p")]
    print(f"正文段落数 = {len(paras)}（期望 28）")

    def P(n: int):
        return paras[n - 1]

    def text_of(el) -> str:
        return Paragraph(el, doc).text

    # ---------- 1. 插入新项目（必须在删段之前做，否则编号会错） ----------
    for ref_n, blocks in INSERT_BEFORE.items():
        ref = P(ref_n)
        for text, bold, kind in blocks:
            tpl = P(17) if kind == "title" else P(20)
            new = deepcopy(tpl)
            set_runs(new, [(text, bold)])
            ref.addprevious(new)          # ← ref 保持不变，顺序才是对的

    # ---------- 2. 改文字 ----------
    for n, content in REWRITE.items():
        if isinstance(content, str):
            set_runs(P(n), [(content, False)])
        else:
            set_runs(P(n), content)

    # ---------- 3. 删段 ----------
    for n in DELETE:
        el = P(n)
        el.getparent().remove(el)

    # ---------- 4. 自我评价（前面删过元素，这里按内容重新定位） ----------
    now = [c for c in body.iterchildren() if c.tag == qn("w:p")]
    head = next(i for i, c in enumerate(now) if text_of(c).strip() == "自我评价")
    tail = now[head + 1:]
    print(f"自我评价下面原来有 {len(tail)} 段")

    for i, text in enumerate(EVAL_TEXT):
        if i < len(tail):
            set_runs(tail[i], [(text, False)])
    for extra in tail[EVAL_KEEP:]:
        extra.getparent().remove(extra)

    doc.save(dst)

    # ---------- 5. 回读确认 ----------
    print(f"\nsaved: {dst}\n")
    check = Document(dst)
    for p in check.paragraphs:
        t = p.text.strip()
        if t:
            print(f"  {t}")
    print(f"\n段落总数 = {len(check.paragraphs)} / 表格数 = {len(check.tables)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
