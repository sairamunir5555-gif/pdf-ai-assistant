# PDF AI Assistant

Upload a PDF in the browser. Get its topics as short bullet points, then ask questions about it.
FastAPI backend, plain HTML/CSS/JS frontend, Nemotron 3 Ultra (free) through OpenRouter.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then put your OPENROUTER_API_KEY in .env
uvicorn backend.app.main:app --port 8000
```

Open http://localhost:8000. The first upload downloads the embedding model once (needs internet).
Docker: `docker build -t pdf-ai . && docker run -p 8000:8000 --env-file .env -v pdf-ai-data:/data pdf-ai`

Note: the free Nemotron endpoint logs prompts. Do not upload confidential PDFs.
Free models have tight request limits, which is why the summary uses few model calls.

## How it works

Upload button -> `POST /api/upload` -> background job: extract pages (PyMuPDF, tables kept as
Markdown) -> chunk -> embed (multilingual-e5) -> store (Chroma on disk). The page polls
`/api/jobs/{id}` for progress. Uploading the same file again is instant (hash of the bytes).

**Asking a question** reads only a few chunks. Retrieval is hybrid: dense embeddings plus BM25
keyword search (word tokenization in `nlp.py`), fused with reciprocal rank fusion. Keyword search is
what finds exact values such as `0.0694` that embeddings miss. A question that names a page ("page 12",
or the page box) reads that whole page, including pages with only a small amount of readable text.
Pages not retrieved are not needed to answer that question.

**Summarizing** must cover every page, so it does not use top-k retrieval:
1. Skip reference pages and empty/image-only pages.
2. Compress each remaining page with extractive NLP (headings plus highest-scoring sentences,
   about 1,400 characters per page). Very short readable pages are kept, with a text fallback when
   there are no complete sentences to extract. No model call.
3. Send the digest to the model: one call up to about 40k characters, otherwise one call per batch
   plus one merge call. Output is topics with informative points and page numbers. The UI's text
   reduction percentage describes compression before the model call, not the percentage of PDF pages
   omitted; page coverage and skipped reference/empty pages are shown separately.
The result is cached per document. The page-coverage strip in the UI shows which pages were read.

A broad question such as "what is this paper about?" is answered from the cached summary, because
top-k chunks cannot represent a whole document.

## Issues found in the Colab prototype, and what changed

| Issue | Change |
|---|---|
| `summarize()` sent every page to the model (12+ calls for 70 pages, sleeping between) and ignored RAG | Extractive compression of all pages, then 1-3 calls, cached |
| No word-level NLP; dense search only, so exact numbers and names were missed (your `0.0694` case) | Tokenizer + BM25 + rank fusion |
| The table-chunk fix from the notebook was never ported to the backend; tables were cut mid-row | Each table is its own chunk with caption and header repeated |
| Reference pages were summarized and indexed as normal content | Reference pages detected and skipped for summaries |
| Page questions retrieved chunks of that page | Whole page is used, so nothing on it is missed |
| Colab-only code (`drive`, `userdata`, `!pip`), cells run by hand | Single app: upload button triggers the pipeline |
| Documents in a global dict plus in-memory Chroma: lost on restart, never freed | Stored on disk, reloaded on demand, expired after 72 hours |
| Upload and summary ran inside one HTTP request (timeouts) | Background jobs with progress polling |
| Size check after reading the whole file; only the `.pdf` extension was checked | Streamed size limit, `%PDF-` check, page limit, password-protected and scanned PDF messages |
| PDF text inserted into prompts without guarding against instructions inside it | Prompts mark document text as untrusted |
| Groq key from Colab secrets | OpenRouter key from `.env`; model `nvidia/nemotron-3-ultra-550b-a55b:free` |

## Known limits

- Scanned (image-only) PDFs are rejected with a clear message; OCR is not included.
- Figures and charts are not read, only text and detected tables.
- Table caption matching is a heuristic (the Nth "Table N:" caption goes with the Nth table).
- Text after the "References" heading on that one page is dropped from the index.
- Documents are stored unencrypted on the server for 72 hours (`DOC_TTL_HOURS`).

## Layout

```
backend/app/  config.py pdf.py nlp.py rag.py summarize.py qa.py llm.py jobs.py main.py
frontend/     index.html style.css app.js
tests/        test_nlp.py
```
