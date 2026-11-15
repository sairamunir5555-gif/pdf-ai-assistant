from html import escape
from io import BytesIO
from pathlib import Path
import tempfile

import pymupdf
from docx import Document


def _summary_html(title: str, summary: dict) -> str:
    parts = [
        f"<h1>{escape(title)} - AI Summary</h1>",
        f"<p class='meta'>Pages read: {len(summary['pages_read'])} of {summary['pages_total']}</p>",
    ]
    for topic in summary["topics"]:
        parts.append(f"<h2>{escape(topic['topic'])}</h2>")
        if topic["pages"]:
            pages = ", ".join(str(page) for page in topic["pages"])
            parts.append(f"<p class='meta'>Pages: {escape(pages)}</p>")
        parts.append("<ul>")
        parts.extend(f"<li>{escape(point)}</li>" for point in topic["points"])
        parts.append("</ul>")
    return "<html><body>" + "".join(parts) + "</body></html>"


def create_pdf(title: str, summary: dict) -> bytes:
    html = _summary_html(title, summary)
    css = """
        body { font-family: sans-serif; font-size: 11pt; color: #111; }
        h1 { font-size: 22pt; margin-bottom: 8pt; }
        h2 { font-size: 15pt; margin-top: 18pt; border-bottom: 2px solid #ff5a00; }
        p { margin: 4pt 0 8pt; }
        .meta { color: #555; font-size: 9pt; }
        ul { padding-left: 18pt; }
        li { margin-bottom: 5pt; }
    """
    story = pymupdf.Story(html=html, user_css=css)
    media_box = pymupdf.paper_rect("a4")
    content_box = pymupdf.Rect(48, 48, media_box.width - 48, media_box.height - 48)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "summary.pdf"
        writer = pymupdf.DocumentWriter(str(path))
        more = True
        while more:
            device = writer.begin_page(media_box)
            more, _ = story.place(content_box)
            story.draw(device)
            writer.end_page()
        writer.close()
        del device, writer
        return path.read_bytes()


def create_docx(title: str, summary: dict) -> bytes:
    document = Document()
    document.add_heading(f"{title} - AI Summary", 0)
    document.add_paragraph(
        f"Pages read: {len(summary['pages_read'])} of {summary['pages_total']}"
    )
    for topic in summary["topics"]:
        document.add_heading(topic["topic"], level=1)
        if topic["pages"]:
            document.add_paragraph("Pages: " + ", ".join(str(page) for page in topic["pages"]))
        for point in topic["points"]:
            document.add_paragraph(point, style="List Bullet")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
