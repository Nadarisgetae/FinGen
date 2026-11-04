"""
FinGen v2 — Export: Markdown to DOCX
Extends CaseGen's markdown_to_docx with chart embedding.
"""

import io
import re
from typing import Dict, List, Optional
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT


def _set_document_styles(doc: Document, font: str = "Times New Roman", size: int = 11):
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    style = doc.styles["Normal"]
    style.font.name = font
    style.font.size = Pt(size)


def _add_table_from_markdown(doc: Document, lines: list):
    if len(lines) < 2:
        return
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        if line.strip().startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])

    if not header:
        return

    table = doc.add_table(rows=1 + len(rows), cols=len(header))
    table.style = "Table Grid"
    for i, h in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    for r_idx, row in enumerate(rows):
        for c_idx, cell_text in enumerate(row[: len(header)]):
            table.rows[r_idx + 1].cells[c_idx].text = cell_text


def _add_chart(doc: Document, image_bytes: bytes, caption: str = None):
    """Embed a PNG image with optional caption."""
    try:
        doc.add_picture(io.BytesIO(image_bytes), width=Inches(6.0))
        doc.paragraphs[-1].alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        if caption:
            p = doc.add_paragraph()
            p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            run = p.add_run(caption)
            run.italic = True
            run.font.size = Pt(9)
    except Exception as e:
        # Chart embedding failed — insert placeholder text
        p = doc.add_paragraph()
        run = p.add_run(f"[Chart unavailable: {e}]")
        run.italic = True


def markdown_to_docx(
    markdown: str,
    charts: Dict[str, bytes] = None,
    title: str = None,
    disclaimers: list = None,
) -> bytes:
    """
    Convert Markdown string to .docx bytes.

    Args:
        markdown: Report markdown
        charts: {placeholder_key: png_bytes} — inserted at <!--chart:key--> markers
        title: Document title (defaults to first H1)
        disclaimers: Footer disclaimer lines
    """
    charts = charts or {}
    doc = Document()
    _set_document_styles(doc)

    # Title page
    if title:
        h = doc.add_heading(title, level=0)
        doc.add_paragraph()

    lines = markdown.splitlines()
    i = 0
    table_buffer = []

    while i < len(lines):
        line = lines[i]

        # Chart marker: <!--chart:chart_name-->
        chart_match = re.match(r"<!--\s*chart:(\S+)\s*-->", line.strip())
        if chart_match:
            chart_name = chart_match.group(1)
            if chart_name in charts:
                _add_chart(doc, charts[chart_name], caption=f"Chart: {chart_name}")
            else:
                p = doc.add_paragraph()
                run = p.add_run(f"[Chart '{chart_name}' not generated]")
                run.italic = True
            i += 1
            continue

        if line.strip().startswith("|"):
            table_buffer.append(line)
            i += 1
            continue
        elif table_buffer:
            _add_table_from_markdown(doc, table_buffer)
            table_buffer = []

        if line.startswith("# "):
            p = doc.add_heading(line[2:].strip(), level=1)
            if p.runs:
                p.runs[0].font.name = "Times New Roman"
        elif line.startswith("## "):
            p = doc.add_heading(line[3:].strip(), level=2)
            if p.runs:
                p.runs[0].font.name = "Times New Roman"
        elif line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
        elif line.strip().startswith("> "):
            raw = line.strip()[2:].strip()
            raw = re.sub(r"\*(.+?)\*", r"\1", raw)
            raw = re.sub(r"_(.+?)_", r"\1", raw)
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.4)
            run = p.add_run(raw)
            run.italic = True
        elif line.strip() == "":
            pass
        else:
            # Bold markers as runs
            p = doc.add_paragraph()
            parts = re.split(r"(\*\*.+?\*\*)", line.strip())
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    run = p.add_run(part)
                run.font.name = "Times New Roman"
                run.font.size = Pt(11)

        i += 1

    if table_buffer:
        _add_table_from_markdown(doc, table_buffer)

    # Disclaimers footer
    if disclaimers:
        doc.add_page_break()
        for d in disclaimers:
            p = doc.add_paragraph()
            run = p.add_run(d)
            run.italic = True
            run.font.size = Pt(9)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()