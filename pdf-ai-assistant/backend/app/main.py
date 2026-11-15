import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import exports, jobs, rag
from .config import ROOT, settings
from .llm import LLMError
from .qa import answer_question
from .summarize import summarize_document, summarize_page

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    rag.purge_old_docs()
    yield


app = FastAPI(title="PDF AI Assistant", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    page: int | None = None


class SummaryRequest(BaseModel):
    page: int | None = None
    refresh: bool = False


class ExportTopic(BaseModel):
    topic: str
    points: list[str]
    pages: list[int] = Field(default_factory=list)


class SummaryExportRequest(BaseModel):
    pages_total: int
    pages_read: list[int]
    topics: list[ExportTopic]


def _doc(doc_id: str):
    try:
        return rag.load_doc(doc_id)
    except KeyError:
        raise HTTPException(404, "Document not found. Please upload the PDF again.")


def _process_uploaded_doc(doc_id: str, name: str, data: bytes, progress) -> dict:
    if rag.doc_exists(doc_id):
        rag.save_original_pdf(doc_id, data)
        progress(0.65, "Using saved PDF index")
    else:
        rag.ingest(
            doc_id,
            name,
            data,
            lambda fraction, message=None: progress(fraction * 0.65, message),
        )

    doc = rag.load_doc(doc_id)
    if not doc.meta.get("summary"):
        progress(0.7, "Summarizing document")
        result = summarize_document(
            doc,
            lambda fraction, message=None: progress(0.7 + fraction * 0.29, message),
        )
        rag.set_summary(doc_id, result)

    progress(1.0, "Ready")
    return rag.public_meta(doc.meta)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_configured": bool(settings.openrouter_api_key), "model": settings.llm_model}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    name = file.filename or "document.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")
    limit = settings.max_upload_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):  # stop early instead of loading a huge file
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    data = bytes(buf)
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "This file is not a valid PDF.")
    doc_id = hashlib.sha256(data).hexdigest()[:16]  # same file again = instant, summary cached
    if rag.doc_exists(doc_id):
        doc = rag.load_doc(doc_id)
        rag.save_original_pdf(doc_id, data)
        if doc.meta.get("summary"):
            return {"job_id": None, "name": name, **rag.public_meta(doc.meta)}
    job_id = jobs.submit(
        f"upload:{doc_id}",
        lambda progress: _process_uploaded_doc(doc_id, name, data, progress),
    )
    return {"job_id": job_id, "doc_id": doc_id, "name": name}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@app.get("/api/docs/{doc_id}")
def doc_info(doc_id: str):
    doc = _doc(doc_id)
    return {**rag.public_meta(doc.meta), "summary": doc.meta.get("summary")}


@app.post("/api/docs/{doc_id}/summary")
def summary(doc_id: str, req: SummaryRequest):
    doc = _doc(doc_id)
    if req.page is not None and not 1 <= req.page <= len(doc.pages):
        raise HTTPException(400, f"This PDF has only {len(doc.pages)} pages.")
    if req.page is None and doc.meta.get("summary") and not req.refresh:
        return {"job_id": None, "result": doc.meta["summary"]}

    def work(progress):
        if req.page is not None:
            return summarize_page(doc, req.page)
        result = summarize_document(doc, progress)
        rag.set_summary(doc_id, result)
        return result

    return {"job_id": jobs.submit(f"summary:{doc_id}:{req.page}", work), "result": None}


@app.post("/api/docs/{doc_id}/summary/export")
def export_summary(doc_id: str, format: Literal["pdf", "docx"], req: SummaryExportRequest):
    doc = _doc(doc_id)
    title = Path(doc.meta.get("name") or "document.pdf").stem
    summary_data = {
        "pages_total": req.pages_total,
        "pages_read": req.pages_read,
        "topics": [
            {"topic": topic.topic, "points": topic.points, "pages": topic.pages}
            for topic in req.topics
        ],
    }
    if format == "pdf":
        content = exports.create_pdf(title, summary_data)
        media_type = "application/pdf"
    else:
        content = exports.create_docx(title, summary_data)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    safe_title = re.sub(r"[^\w.-]+", "-", title, flags=re.UNICODE).strip("-.") or "document"
    filename = quote(f"{safe_title}-summary.{format}")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.post("/api/docs/{doc_id}/ask")
def ask(doc_id: str, req: AskRequest):
    doc = _doc(doc_id)
    if not req.question.strip():
        raise HTTPException(400, "Question is empty.")
    try:
        return answer_question(doc, req.question.strip(), req.page)
    except LLMError as e:
        raise HTTPException(502, str(e))


# Frontend (plain HTML/CSS/JS) is served from the same origin, so no CORS setup is needed.
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
