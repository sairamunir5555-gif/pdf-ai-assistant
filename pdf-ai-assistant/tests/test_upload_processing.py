from types import SimpleNamespace

from backend.app import main


def _doc(doc_id, summary=None):
    return SimpleNamespace(
        meta={"doc_id": doc_id, "name": "sample.pdf", "pages": 2, "summary": summary}
    )


def test_new_upload_indexes_then_saves_summary(monkeypatch):
    doc_id = "0123456789abcdef"
    doc = _doc(doc_id)
    calls = []

    monkeypatch.setattr(main.rag, "doc_exists", lambda value: False)

    def fake_ingest(value, name, data, progress):
        calls.append("ingest")
        progress(1, "Indexed")

    monkeypatch.setattr(main.rag, "ingest", fake_ingest)
    monkeypatch.setattr(main.rag, "load_doc", lambda value: doc)
    monkeypatch.setattr(
        main,
        "summarize_document",
        lambda value, progress: calls.append("summarize") or {"topics": []},
    )
    monkeypatch.setattr(
        main.rag,
        "set_summary",
        lambda value, summary: doc.meta.update(summary=summary),
    )
    progress = []

    result = main._process_uploaded_doc(doc_id, "sample.pdf", b"%PDF-1.7", lambda *args: progress.append(args))

    assert calls == ["ingest", "summarize"]
    assert result["has_summary"] is True
    assert progress[-1] == (1.0, "Ready")


def test_existing_index_without_summary_is_not_rebuilt(monkeypatch):
    doc_id = "0123456789abcdef"
    doc = _doc(doc_id)
    saved = []

    monkeypatch.setattr(main.rag, "doc_exists", lambda value: True)
    monkeypatch.setattr(main.rag, "save_original_pdf", lambda value, data: saved.append(data))
    monkeypatch.setattr(
        main.rag,
        "ingest",
        lambda *args: (_ for _ in ()).throw(AssertionError("existing index was rebuilt")),
    )
    monkeypatch.setattr(main.rag, "load_doc", lambda value: doc)
    monkeypatch.setattr(main, "summarize_document", lambda value, progress: {"topics": []})
    monkeypatch.setattr(
        main.rag,
        "set_summary",
        lambda value, summary: doc.meta.update(summary=summary),
    )

    result = main._process_uploaded_doc(doc_id, "sample.pdf", b"%PDF-1.7", lambda *args: None)

    assert saved == [b"%PDF-1.7"]
    assert result["has_summary"] is True
