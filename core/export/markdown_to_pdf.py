"""
FinGen v2 — Export: Markdown to PDF
Extends CaseGen's markdown_to_pdf with chart embedding.
Prefers WeasyPrint; falls back to xhtml2pdf (pure Python, Windows-friendly).
"""

import io
import re
import base64


def _embed_image_as_data_uri(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")


def _markdown_to_html(markdown: str, charts: dict = None) -> str:
    charts = charts or {}
    html_parts = []
    lines = markdown.splitlines()
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows:
            return
        html_parts.append(
            "<table border='1' cellpadding='6' cellspacing='0' "
            "style='width:100%;margin:12px 0;font-size:10pt;'>"
        )
        for ri, row in enumerate(table_rows):
            tag = "th" if ri == 0 else "td"
            html_parts.append("<tr>")
            for cell in row:
                cell_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", cell)
                html_parts.append(f"<{tag}>{cell_html}</{tag}>")
            html_parts.append("</tr>")
        html_parts.append("</table>")
        table_rows = []
        in_table = False

    for line in lines:
        # Chart marker
        chart_match = re.match(r"<!--\s*chart:(\S+)\s*-->", line.strip())
        if chart_match:
            chart_name = chart_match.group(1)
            if chart_name in charts:
                data_uri = _embed_image_as_data_uri(charts[chart_name])
                html_parts.append(
                    f"<div style='text-align:center;margin:16px 0;'>"
                    f"<img src='{data_uri}' style='max-width:100%;height:auto;'/>"
                    f"<div style='font-size:9pt;color:#666;font-style:italic;margin-top:4px;'>Chart: {chart_name}</div>"
                    f"</div>"
                )
            else:
                html_parts.append(f"<p><em>[Chart '{chart_name}' not generated]</em></p>")
            continue

        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue
            table_rows.append(cells)
            in_table = True
            continue
        elif in_table:
            flush_table()

        if line.startswith("# "):
            html_parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_parts.append(f"<h3>{line[4:]}</h3>")
        elif line.strip().startswith("> "):
            raw = line.strip()[2:].strip()
            raw = re.sub(r"\*(.+?)\*", r"\1", raw)
            raw = re.sub(r"_(.+?)_", r"\1", raw)
            html_parts.append(f"<blockquote><em>{raw}</em></blockquote>")
        elif line.strip():
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            text = re.sub(
                r"\[([^\]]+)\]\((https?://[^)]+)\)",
                r'<a href="\2" style="word-break:break-all;overflow-wrap:anywhere;">\1</a>',
                text,
            )
            html_parts.append(f"<p>{text}</p>")

    if in_table:
        flush_table()

    body = "\n".join(html_parts)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@page {{ margin: 1in; }}
body {{ font-family: 'Times New Roman', Times, serif; font-size: 11pt; line-height: 1.5; color: #000; }}
h1 {{ font-size: 18pt; }} h2 {{ font-size: 14pt; margin-top: 18px; }} h3 {{ font-size: 12pt; }}
table {{ page-break-inside: avoid; }}
tr {{ page-break-inside: avoid; page-break-after: auto; }}
blockquote {{ border-left: 3px solid #555; margin: 12px 0 12px 20px; padding: 4px 12px; font-style: italic; color: #333; }}
a {{ word-break: break-all; overflow-wrap: anywhere; color: #1a0dab; }}
.disclaimer {{ font-size: 8pt; color: #666; font-style: italic; margin-top: 24px; border-top: 1px solid #ccc; padding-top: 12px; }}
</style></head><body>{body}</body></html>"""


def markdown_to_pdf(
    markdown: str,
    charts: dict = None,
    disclaimers: list = None,
) -> bytes:
    """
    Convert Markdown to PDF bytes.

    Args:
        markdown: Report markdown
        charts: {placeholder_key: png_bytes}
        disclaimers: Footer disclaimer lines
    """
    if disclaimers:
        disclaimer_html = "<div class='disclaimer'>" + "<br/>".join(disclaimers) + "</div>"
        # Append to body by injecting before </body>
        html = _markdown_to_html(markdown, charts)
        html = html.replace("</body>", disclaimer_html + "</body>")
    else:
        html = _markdown_to_html(markdown, charts)

    # 1. Preferred: WeasyPrint
    try:
        from weasyprint import HTML
        pdf_buffer = io.BytesIO()
        HTML(string=html).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        return pdf_buffer.read()
    except (ImportError, OSError):
        pass

    # 2. Fallback: xhtml2pdf (pure-Python, Windows-friendly)
    try:
        from xhtml2pdf import pisa
        pdf_buffer = io.BytesIO()
        result = pisa.CreatePDF(src=html, dest=pdf_buffer)
        if result.err:
            raise RuntimeError("xhtml2pdf failed to render the document.")
        pdf_buffer.seek(0)
        return pdf_buffer.read()
    except ImportError as e:
        raise RuntimeError(
            "PDF export needs either 'weasyprint' or 'xhtml2pdf'. "
            "Install one (xhtml2pdf is easiest on Windows), or use the Word export."
        ) from e