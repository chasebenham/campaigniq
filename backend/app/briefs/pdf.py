"""Letter-size rendering of the immutable executive document."""

import re
import unicodedata
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from app.briefs.schemas import Document, Table

INK = colors.HexColor("#17253C")
MUTED = colors.HexColor("#53637C")
BLUE = colors.HexColor("#254FBC")
LINE = colors.HexColor("#DDE5F1")
PALE = colors.HexColor("#F2F6FC")
LABELS = {
    "verified": "VERIFIED EVIDENCE", "ai": "AI INTERPRETATION",
    "management": "MANAGEMENT", "modeled": "HYPOTHETICAL",
}


def safe_markup(value: str) -> str:
    cleaned = "".join(char for char in value if char in "\n\t" or not unicodedata.category(char).startswith("C"))
    normalized = re.sub(r"[\u2010-\u2015\u2212]", "-", cleaned)
    return "<br/>".join(escape(line) for line in normalized.splitlines())


def styles():
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=9.6, leading=13.4, textColor=INK,
                          spaceAfter=5, splitLongWords=True, allowWidows=0, allowOrphans=0)
    small = ParagraphStyle("Small", parent=body, fontSize=8.3, leading=11.2, textColor=MUTED)
    return {
        "body": body,
        "meta": small,
        "table_note": ParagraphStyle("TableNote", parent=small, keepWithNext=True),
        "eyebrow": ParagraphStyle("Eyebrow", parent=small, fontName="Helvetica-Bold", textColor=BLUE,
                                  spaceAfter=8, keepWithNext=True),
        "title": ParagraphStyle("Title", parent=body, fontName="Helvetica-Bold", fontSize=25, leading=29,
                                spaceAfter=10, keepWithNext=True),
        "section": ParagraphStyle("Section", parent=body, fontName="Helvetica-Bold", fontSize=15, leading=19,
                                  textColor=BLUE, spaceBefore=12, spaceAfter=6, keepWithNext=True),
        "block": ParagraphStyle("Block", parent=body, fontName="Helvetica-Bold", fontSize=11, leading=14,
                                spaceBefore=6, spaceAfter=5, keepWithNext=True),
        "bullet": ParagraphStyle("Bullet", parent=body, leftIndent=11, firstLineIndent=-9),
        "table": ParagraphStyle("Table", parent=body, fontSize=8.5, leading=11.5, spaceAfter=0),
        "right": ParagraphStyle("Right", parent=body, fontSize=8.5, leading=11.5, spaceAfter=0, alignment=TA_RIGHT),
        "table_header": ParagraphStyle("TableHeader", parent=body, fontName="Helvetica-Bold",
                                       fontSize=8.5, leading=11.5, spaceAfter=0),
    }


def flow_table(table: Table, available_width, style, padding=5):
    right = ParagraphStyle("RightHeader", parent=style["table_header"], alignment=TA_RIGHT)
    cells = [[Paragraph(safe_markup(label), style["table_header"] if index == 0 else right)
              for index, label in enumerate(table.headers)]]
    for row in table.rows:
        cells.append([Paragraph(safe_markup(item), style["table" if index == 0 else "right"])
                      for index, item in enumerate(row)])
    first_ratio = 0.38 if len(table.headers) <= 4 else 0.22
    widths = [available_width * first_ratio] + [
        available_width * (1 - first_ratio) / (len(table.headers) - 1)
    ] * (len(table.headers) - 1)
    result = LongTable(cells, colWidths=widths, repeatRows=1, hAlign="LEFT", spaceBefore=4, spaceAfter=6)
    result.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), padding), ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]))
    return result


def render_pdf(document: Document, version: int) -> bytes:
    buffer = BytesIO()
    width, height = letter
    margin = 54
    report = SimpleDocTemplate(buffer, pagesize=letter, topMargin=53, bottomMargin=55, leftMargin=margin,
                               rightMargin=margin, title=document.title, author="CampaignIQ")
    style = styles()

    def para(value: str, name: str = "body"):
        return Paragraph(safe_markup(value), style[name])

    generated = document.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    inline_drafting = document.template_version == "1.1.0"
    story = [
        para("CAMPAIGNIQ  /  NORTHSTAR OUTFITTERS", "eyebrow"), para(document.title, "title"),
        para(f"Reporting period {document.period.start} to {document.period.end} | Version {version}", "meta"),
        para(f"Generated {generated} | Fictional Northstar Outfitters", "meta"),
        para(document.provenance, "meta"), Spacer(1, 5),
    ]
    for section in document.sections:
        section_heading = para(section.title, "section")
        for index, block in enumerate(section.blocks):
            content = [section_heading] if index == 0 else []
            title = block.title
            if block.source:
                title = f"{title}  /  {LABELS[block.source]}" if title else None
                if not title:
                    content.append(para(LABELS[block.source], "eyebrow"))
            if title:
                content.append(para(title, "block"))
            for paragraph in block.paragraphs:
                role = "table_note" if inline_drafting and paragraph.startswith("Accepted AI Analyst #") else "body"
                content.append(para(paragraph, role))
            for table in block.tables:
                if table.caption and inline_drafting:
                    content.append(para(table.caption, "table_note"))
                content.append(flow_table(table, report.width - 12, style, padding=4 if inline_drafting else 5))
                if table.caption and not inline_drafting:
                    content.append(para(table.caption, "meta"))
            for bullet in block.bullets:
                content.append(para(f"•  {bullet}", "bullet"))
            if section.title == "Prioritized Findings" and block.title:
                story.append(KeepTogether(content))
            else:
                story.extend(content)

    def frame(canvas: Canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(.7)
        canvas.line(margin, 41, width - margin, 41)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(margin, 28, f"CampaignIQ  /  Northstar Outfitters (fictional)  /  {document.generated_at.date()}")
        canvas.drawRightString(width - margin, 28, f"Version {version}  /  Page {canvas.getPageNumber()}")
        if canvas.getPageNumber() > 1:
            canvas.setFont("Helvetica-Bold", 8.5)
            canvas.drawString(margin, height - 32, "CAMPAIGNIQ  /  EXECUTIVE STRATEGY BRIEF")
        canvas.restoreState()

    report.build(story, onFirstPage=frame, onLaterPages=frame)
    return buffer.getvalue()


def filename(title: str, version: int) -> str:
    safe = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", safe.lower()).strip("-")[:75].rstrip("-")
    return f"{slug or 'strategy-brief'}-v{version}.pdf"
