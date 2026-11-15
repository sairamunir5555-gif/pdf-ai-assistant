from backend.app.nlp import BM25, build_idf, compress, rrf, tokenize
from backend.app.summarize import parse_topics


def test_tokenize_keeps_numbers_and_compounds():
    toks = tokenize("The C4 loss was 0.0694 with a state-of-the-art model")
    assert "0.0694" in toks and "state-of-the-art" in toks and "art" in toks


def test_bm25_finds_exact_number():
    docs = [tokenize(t) for t in ["loss was 0.0694 on C4", "general discussion of models", "unrelated text here"]]
    assert BM25(docs).top(tokenize("0.0694"), 3)[0] == 0


def test_rrf_prefers_items_in_both_lists():
    assert rrf([["a", "b", "c"], ["c", "a", "d"]])[0] == "a"


def test_compress_respects_budget_and_keeps_heading():
    text = "1. Introduction\n" + " ".join(
        f"Sentence number {i} talks about dataset {i} and method {i} in detail." for i in range(40))
    out = compress(text, build_idf([text]), 300)
    assert out.startswith("1. Introduction") and len(out) <= 310


def test_parse_topics_json_and_fallback():
    raw = '```json\n{"topics":[{"topic":"A","points":["x y z"],"pages":[1,99]}]}\n```'
    assert parse_topics(raw, 10)[0]["pages"] == [1]
    assert parse_topics("- first point is long enough\n- second point is long enough", 10)[0]["topic"] == "Summary"
