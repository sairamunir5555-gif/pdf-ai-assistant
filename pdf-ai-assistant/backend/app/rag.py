"""Document storage and hybrid retrieval (dense embeddings + BM25 keywords, fused with RRF)."""
import json
import os
import re
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

from .config import settings
from .nlp import BM25, rrf, tokenize
from .pdf import Page, extract_pages

DOC_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_model_lock = threading.Lock()
_cache_lock = threading.Lock()
_embedder = None
_chroma = None
_cache: "OrderedDict[str, Doc]" = OrderedDict()


def doc_path(doc_id: str) -> Path:
    if not DOC_ID_RE.match(doc_id):  # also blocks path traversal
        raise KeyError(doc_id)
    return settings.data_dir / "docs" / doc_id


def get_embedder():
    global _embedder
    with _model_lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer

            _embedder = SentenceTransformer(settings.embed_model)
        return _embedder


def get_chroma():
    global _chroma
    with _model_lock:
        if _chroma is None:
            import chromadb

            _chroma = chromadb.PersistentClient(path=str(settings.data_dir / "chroma"))
        return _chroma


def _split_table(caption: str, md: str, limit: int = 1500) -> list:
    """Tables become their own chunks (caption + header repeated), so numbers stay findable."""
    lines = md.splitlines()
    prefix = (caption + "\n" if caption else "") + "\n".join(lines[:2])
    rows = lines[2:]
    out, cur, size = [], [], len(prefix)
    for r in rows:
        if cur and size + len(r) + 1 > limit:
            out.append(prefix + "\n" + "\n".join(cur))
            cur, size = [], len(prefix)
        cur.append(r)
        size += len(r) + 1
    if cur or not out:
        out.append(prefix + ("\n" + "\n".join(cur) if cur else ""))
    return out


def build_chunks(pages: list) -> list:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
    )
    chunks = []
    for p in pages:
        body = p.body.strip()
        for j, piece in enumerate(splitter.split_text(body) if body else []):
            chunks.append({"id": f"p{p.number}-c{j}", "text": piece, "page": p.number, "kind": "text"})
        for t, (cap, md) in enumerate(p.tables):
            for s, piece in enumerate(_split_table(cap, md)):
                chunks.append({"id": f"p{p.number}-t{t}-{s}", "text": piece, "page": p.number, "kind": "table"})
    return chunks


def _index_chunks(doc_id: str, chunks: list, progress) -> None:
    client = get_chroma()
    name = f"doc_{doc_id}"
    try:
        client.delete_collection(name)
    except Exception:
        pass
    col = client.create_collection(name, metadata={"hnsw:space": "cosine"})
    embedder = get_embedder()
    step = 32
    for i in range(0, len(chunks), step):
        b = chunks[i:i + step]
        vecs = embedder.encode(["passage: " + c["text"] for c in b], normalize_embeddings=True).tolist()
        col.add(
            ids=[c["id"] for c in b],
            documents=[c["text"] for c in b],
            embeddings=vecs,
            metadatas=[{"page": c["page"], "kind": c["kind"]} for c in b],
        )
        progress(min(1.0, (i + step) / len(chunks)))


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def ingest(doc_id: str, name: str, data: bytes, progress) -> dict:
    """Upload pipeline: extract -> chunk -> embed -> store. meta.json is written last (ready marker)."""
    d = doc_path(doc_id)
    d.mkdir(parents=True, exist_ok=True)
    progress(0.02, "Reading PDF pages")
    pages = extract_pages(data, settings.max_pages,
                          lambda f: progress(0.02 + 0.28 * f, "Reading PDF pages"))
    chunks = build_chunks(pages)
    if not chunks:
        raise ValueError("No readable text found in this PDF.")
    progress(0.30, "Building search index")
    _index_chunks(doc_id, chunks, lambda f: progress(0.30 + 0.68 * f, "Building search index"))
    _write_json(d / "pages.json", [asdict(p) for p in pages])
    _write_json(d / "chunks.json", chunks)
    meta = {"doc_id": doc_id, "name": name, "pages": len(pages), "created": time.time(), "summary": None}
    _write_json(d / "meta.json", meta)
    progress(1.0, "Ready")
    return public_meta(meta)


def public_meta(meta: dict) -> dict:
    return {"doc_id": meta["doc_id"], "name": meta["name"], "pages": meta["pages"],
            "has_summary": bool(meta.get("summary"))}


def doc_exists(doc_id: str) -> bool:
    return (doc_path(doc_id) / "meta.json").exists()


class Doc:
    def __init__(self, doc_id: str):
        d = doc_path(doc_id)
        if not (d / "meta.json").exists():
            raise KeyError(doc_id)
        self.id = doc_id
        self.meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        self.pages = [Page(**p) for p in json.loads((d / "pages.json").read_text(encoding="utf-8"))]
        self.chunks = json.loads((d / "chunks.json").read_text(encoding="utf-8"))
        self.by_id = {c["id"]: c for c in self.chunks}
        self.bm25 = BM25([tokenize(c["text"]) for c in self.chunks])


def load_doc(doc_id: str) -> Doc:
    with _cache_lock:
        if doc_id in _cache:
            _cache.move_to_end(doc_id)
            return _cache[doc_id]
    doc = Doc(doc_id)
    os.utime(doc_path(doc_id))  # keeps active documents from expiring
    with _cache_lock:
        _cache[doc_id] = doc
        while len(_cache) > 8:
            _cache.popitem(last=False)
    return doc


def set_summary(doc_id: str, summary: dict) -> None:
    doc = load_doc(doc_id)
    doc.meta["summary"] = summary
    _write_json(doc_path(doc_id) / "meta.json", doc.meta)


def retrieve(doc: Doc, question: str, k: int | None = None) -> list:
    """Top chunks by dense similarity AND keyword match, fused with reciprocal rank fusion."""
    n = settings.candidates
    col = get_chroma().get_collection(f"doc_{doc.id}")
    q = get_embedder().encode(["query: " + question], normalize_embeddings=True).tolist()
    dense = col.query(query_embeddings=q, n_results=min(n, col.count()))["ids"][0]
    sparse = [doc.chunks[i]["id"] for i in doc.bm25.top(tokenize(question), n)]
    fused = rrf([dense, sparse])[: k or settings.top_k]
    return [doc.by_id[i] for i in fused if i in doc.by_id]


def purge_old_docs() -> None:
    base = settings.data_dir / "docs"
    if not base.exists():
        return
    cutoff = time.time() - settings.doc_ttl_hours * 3600
    for d in base.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                try:
                    get_chroma().delete_collection(f"doc_{d.name}")
                except Exception:
                    pass
        except OSError:
            pass
