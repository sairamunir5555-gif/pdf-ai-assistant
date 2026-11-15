from types import SimpleNamespace

from backend.app import qa
from backend.app.pdf import Page
from backend.app import summarize


def test_page_question_uses_short_readable_text(monkeypatch):
    page = Page(1, "A short but readable page. " * 10)
    doc = SimpleNamespace(id="0123456789abcdef", pages=[page], meta={})
    calls = []

    def fake_chat(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return "The answer is in the page."

    monkeypatch.setattr(qa.llm, "chat", fake_chat)
    monkeypatch.setattr(qa.rag, "get_cached_answer", lambda *args: None)
    monkeypatch.setattr(qa.rag, "cache_answer", lambda *args: None)

    result = qa.answer_question(doc, "What is this page about?", page=1)

    assert result["answer"] == "The answer is in the page."
    assert result["pages"] == [1]
    assert calls and "[Page 1]" in calls[0][0]


def test_repeated_question_uses_persistent_answer_cache(monkeypatch, tmp_path):
    doc_id = "0123456789abcdef"
    (tmp_path / "docs" / doc_id).mkdir(parents=True)
    monkeypatch.setattr(qa.rag.settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        qa.rag,
        "retrieve",
        lambda doc, question: [{"page": 1, "text": "The result is 0.0694."}],
    )
    calls = []

    def fake_chat(prompt, **kwargs):
        calls.append(prompt)
        return "The result is 0.0694 (p. 1)."

    monkeypatch.setattr(qa.llm, "chat", fake_chat)
    first_doc = SimpleNamespace(id=doc_id, pages=[Page(1, "The result is 0.0694.")], meta={})
    second_doc = SimpleNamespace(id=doc_id, pages=[Page(1, "The result is 0.0694.")], meta={})

    first = qa.answer_question(first_doc, "What is the result?")
    second = qa.answer_question(second_doc, "  WHAT is the result? ")

    assert first == second
    assert len(calls) == 1
    assert (tmp_path / "docs" / doc_id / "answers.json").exists()


def test_empty_page_is_rejected_without_calling_model(monkeypatch):
    doc = SimpleNamespace(pages=[Page(1)], meta={})
    calls = []

    def fake_chat(*args, **kwargs):
        calls.append((args, kwargs))
        return "unexpected"

    monkeypatch.setattr(qa.llm, "chat", fake_chat)

    result = qa.answer_question(doc, "What is on this page?", page=1)

    assert "no readable text" in result["answer"]
    assert calls == []


def test_short_readable_page_can_be_summarized(monkeypatch):
    doc = SimpleNamespace(pages=[Page(1, "Short but readable text.")])
    calls = []

    def fake_chat(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return '{"topics":[{"topic":"Quick","points":["Short text is summarized."],"pages":[1]}]}'

    monkeypatch.setattr(summarize.llm, "chat", fake_chat)

    result = summarize.summarize_page(doc, 1)

    assert result["pages_read"] == [1]
    assert result["topics"][0]["topic"] == "Quick"
    assert calls


def test_document_summary_keeps_short_readable_pages(monkeypatch):
    page = Page(1, "Short but readable.")
    doc = SimpleNamespace(pages=[page])
    calls = []

    def fake_chat(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return '{"topics":[{"topic":"Quick","points":["Short text is summarized."],"pages":[1]}]}'

    monkeypatch.setattr(summarize.llm, "chat", fake_chat)

    result = summarize.summarize_document(doc)

    assert result["pages_read"] == [1]
    assert result["pages_skipped"] == {"references": [], "empty": []}
    assert "[p.1] Short but readable." in calls[0][0]


def test_document_summary_keeps_more_page_detail(monkeypatch):
    detail = "We demonstrate the primary mechanism, " + "additional supporting detail " * 35
    detail += " distinctive_conclusion_marker."
    doc = SimpleNamespace(pages=[Page(1, detail)])

    def fake_chat(prompt, **kwargs):
        assert "distinctive_conclusion_marker" in prompt
        assert "detailed, useful summary" in prompt
        return '{"topics":[{"topic":"Findings","points":["The mechanism is explained."],"pages":[1]}]}'

    monkeypatch.setattr(summarize.llm, "chat", fake_chat)

    result = summarize.summarize_document(doc)

    assert result["pages_read"] == [1]


def test_small_document_summary_sends_full_text_from_every_page(monkeypatch):
    pages = [
        Page(n, f"Page {n} includes " + "important supporting information " * 150
             + f" unique_page_marker_{n}.")
        for n in range(1, 5)
    ]
    doc = SimpleNamespace(pages=pages)
    calls = []

    def fake_chat(prompt, **kwargs):
        calls.append(prompt)
        return '{"topics":[{"topic":"Details","points":["All page content is included."],"pages":[1,2,3,4]}]}'

    monkeypatch.setattr(summarize.llm, "chat", fake_chat)

    result = summarize.summarize_document(doc)

    assert result["pages_read"] == [1, 2, 3, 4]
    assert result["stats"]["summary_source"] == "full_text"
    assert result["stats"]["reduction_percent"] == 0
    assert all(f"unique_page_marker_{n}" in calls[0] for n in range(1, 5))
