"""页码 · 封面页不标，正文从 1 起。"""
from __future__ import annotations

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _fld(paragraph, instr: str) -> None:
    run1 = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run1._r.append(begin)

    run2 = paragraph.add_run()
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = f" {instr} "
    run2._r.append(text)

    run3 = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run3._r.append(end)


def add_page_numbers(doc, *, skip_first: bool = True) -> None:
    if not doc.sections:
        return
    section = doc.sections[0]
    if skip_first:
        section.different_first_page_header_footer = True
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for child in list(p._p):
        if child.tag.endswith("}r"):
            p._p.remove(child)
    _fld(p, "PAGE")
