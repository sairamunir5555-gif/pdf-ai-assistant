from types import SimpleNamespace

from backend.app import qa
from backend.app.pdf import Page
from backend.app import summarize


def test_page_question_uses_short_readable_text(monkeypatch):
    page = Page(1, "A short but readable page. " * 10)
    doc = SimpleNamespace(pages=[page], meta={})
    calls = []

    def fake_chat(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return "The answer is in the page."

    monkeypatch.setattr(qa.llm, "chat", fake_chat)

    result = qa.answer_question(doc, "What is this page about?", page=1)

    assert result["answer"] == "The answer is in the page."
    assert result["pages"] == [1]
    assert calls and "[Page 1]" in calls[0][0]


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
