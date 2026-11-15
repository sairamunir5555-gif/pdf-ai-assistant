"""PDF extraction. Runs behind the Upload button on every upload."""
import re
from dataclasses import dataclass, field

LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
CAPTION_RE = re.compile(r"Table\s+\d+[:.][^\n]{0,250}")
REF_HEAD_RE = re.compile(r"^(\d+\.?\s*)?(references|bibliography)$", re.I)


@dataclass
class Page:
    number: int
    body: str = ""
    tables: list = field(default_factory=list)  # [(caption, markdown), ...]
    is_ref: bool = False

    @property
    def text(self) -> str:
        parts = [self.body] + [f"{c}\n{m}".strip() for c, m in self.tables]
        return "\n\n".join(p for p in parts if p).strip()


def clean_text(t: str) -> str:
    """Fix ligatures, join hyphenated line breaks, join wrapped lines of one block."""
    for k, v in LIGATURES.items():
        t = t.replace(k, v)
    t = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", t)
    t = re.sub(r"[ \t]*\n[ \t]*", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _page_parts(page, pymupdf):
    try:
        tabs = page.find_tables().tables
    except Exception:
        tabs = []
    rects = [pymupdf.Rect(t.bbox) for t in tabs]
    body = []
    for b in page.get_text("blocks"):
        if b[6] != 0:  # image block
            continue
        r = pymupdf.Rect(b[:4])
        area = r.get_area()
        if area > 0 and any((r & tr).get_area() > 0.5 * area for tr in rects):
            continue  # this block is inside a table; the table is stored separately
        txt = clean_text(b[4])
        if txt:
            body.append(txt)
    body_text = "\n".join(body)
    captions = CAPTION_RE.findall(body_text)
    tables = []
    for i, t in enumerate(tabs):
        try:
            md = t.to_markdown().strip()
        except Exception:
            continue
        if md:
            tables.append((captions[i].strip() if i < len(captions) else "", md))
    return body_text, tables


def _looks_like_refs(text: str) -> bool:
    years = len(re.findall(r"\b(?:19|20)\d{2}\b", text))
    authors = len(re.findall(r"\b[A-Z][a-z]+, [A-Z]\.", text))
    return years >= 12 or authors > 8


def mark_references(pages: list) -> None:
    """Find the reference list so summaries can skip it.

    The text after the 'References' heading on that one page is dropped. Later pages
    are flagged only if they look like citations, so appendices after the
    references are still summarised.
    """
    n = len(pages)
    start = None
    for i in range(n - 1, int(n * 0.3) - 1, -1):
        lines = pages[i].body.split("\n")
        for j, line in enumerate(lines):
            if REF_HEAD_RE.match(line.strip()):
                start = (i, j)
                break
        if start:
            break
    if not start:
        return
    i, j = start
    pages[i].body = "\n".join(pages[i].body.split("\n")[:j])
    if len(pages[i].text) < 150:
        pages[i].is_ref = True
    for k in range(i + 1, n):
        if _looks_like_refs(pages[k].text):
            pages[k].is_ref = True


def extract_pages(data: bytes, max_pages: int, progress=None) -> list:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass:
            raise ValueError("This PDF is password protected.")
        n = doc.page_count
        if n > max_pages:
            raise ValueError(f"This PDF has {n} pages. The limit is {max_pages}.")
        pages = []
        for i in range(n):
            body, tables = _page_parts(doc[i], pymupdf)
            pages.append(Page(i + 1, body, tables))
            if progress:
                progress((i + 1) / n)
    finally:
        doc.close()
    if sum(len(p.text) for p in pages) < 200:
        raise ValueError(
            "No readable text found. This looks like a scanned (image-only) PDF; OCR is not included."
        )
    mark_references(pages)
    return pages
