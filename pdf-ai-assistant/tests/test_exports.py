from io import BytesIO
from types import SimpleNamespace

import pymupdf
from docx import Document
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.exports import create_docx, create_pdf


SUMMARY = {
    "pages_total": 12,
    "pages_read": list(range(1, 13)),
    "topics": [
        {
            "topic": "Research & results",
            "points": ["The method improved results by 20%."],
            "pages": [2, 5],
        }
    ],
}


def test_pdf_export_contains_summary_text():
    content = create_pdf("Sample document", SUMMARY)

    with pymupdf.open(stream=content, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)

    assert "Sample document" in text
    assert "Research & results" in text
    assert "improved results by 20%" in text


def test_word_export_contains_summary_text():
    content = create_docx("Sample document", SUMMARY)
    document = Document(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert "Sample document" in text
    assert "Research & results" in text
    assert "improved results by 20%" in text


def test_export_endpoint_returns_download_attachments(monkeypatch):
    monkeypatch.setattr(
        main, "_doc", lambda doc_id: SimpleNamespace(meta={"name": "Sample document.pdf"})
    )
    client = TestClient(main.app)

    pdf = client.post(
        "/api/docs/0123456789abcdef/summary/export?format=pdf", json=SUMMARY
    )
    word = client.post(
        "/api/docs/0123456789abcdef/summary/export?format=docx", json=SUMMARY
    )

    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    assert "attachment;" in pdf.headers["content-disposition"]
    assert word.status_code == 200
    assert word.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert word.content.startswith(b"PK")
