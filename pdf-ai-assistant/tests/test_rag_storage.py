import os
import time

from backend.app import rag


def test_original_pdf_is_saved_and_not_overwritten(monkeypatch, tmp_path):
    doc_id = "0123456789abcdef"
    monkeypatch.setattr(rag.settings, "data_dir", tmp_path)
    original = b"%PDF-1.7\noriginal"

    rag.save_original_pdf(doc_id, original)
    rag.save_original_pdf(doc_id, b"%PDF-1.7\nreplacement")

    assert (tmp_path / "docs" / doc_id / "original.pdf").read_bytes() == original


def test_zero_ttl_keeps_documents_persistently(monkeypatch, tmp_path):
    doc_id = "0123456789abcdef"
    doc_dir = tmp_path / "docs" / doc_id
    doc_dir.mkdir(parents=True)
    marker = doc_dir / "original.pdf"
    marker.write_bytes(b"%PDF-1.7")
    old_time = time.time() - 10 * 365 * 24 * 60 * 60
    os.utime(doc_dir, (old_time, old_time))
    monkeypatch.setattr(rag.settings, "data_dir", tmp_path)
    monkeypatch.setattr(rag.settings, "doc_ttl_hours", 0)

    rag.purge_old_docs()

    assert marker.exists()
