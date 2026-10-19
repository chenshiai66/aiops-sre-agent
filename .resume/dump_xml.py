"""导出指定段落的原始 XML，用来确认 run 的格式设置。

用法：
    <python> dump_xml.py <输入.docx> <输出.txt> [段落序号...]
    段落序号按 resume_dump 里的 [Pxxx] 编号（1 起）。
"""

import sys
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph
from lxml import etree


def main(docx: str, out: str, wanted: list[int]):
    doc = Document(docx)
    body = doc.element.body

    idx = 0
    chunks = []
    for child in body.iterchildren():
        if child.tag.split("}")[-1] != "p":
            continue
        idx += 1
        if idx not in wanted:
            continue
        p = Paragraph(child, doc)
        xml = etree.tostring(child, pretty_print=True, encoding="unicode")
        chunks.append(f"{'=' * 70}\n[P{idx:03d}] {p.text!r}\n{'=' * 70}\n{xml}")

    Path(out).write_text("\n".join(chunks), encoding="utf-8")
    print(f"written: {out}  ({len(chunks)} paragraphs)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]])
