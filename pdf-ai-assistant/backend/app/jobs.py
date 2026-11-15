"""Background jobs, so uploads and summaries do not block or time out an HTTP request.
The frontend polls /api/jobs/{id}."""
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .llm import LLMError

log = logging.getLogger("jobs")
_pool = ThreadPoolExecutor(max_workers=2)
_jobs: dict = {}
_keys: dict = {}
_lock = threading.Lock()


def _prune() -> None:
    now = time.time()
    for jid in [j for j, v in _jobs.items() if v["status"] != "running" and now - v["updated"] > 3600]:
        _keys.pop(_jobs[jid]["key"], None)
        del _jobs[jid]


def submit(key: str, fn) -> str:
    """Run fn(progress) in the background. A running job with the same key is reused."""
    with _lock:
        _prune()
        jid = _keys.get(key)
        if jid and jid in _jobs and _jobs[jid]["status"] == "running":
            return jid
        jid = uuid.uuid4().hex[:12]
        _jobs[jid] = {"id": jid, "key": key, "status": "running", "progress": 0.0,
                      "message": "Starting", "result": None, "error": None, "updated": time.time()}
        _keys[key] = jid

    def progress(fraction: float, message: str | None = None) -> None:
        with _lock:
            j = _jobs[jid]
            j["progress"] = round(max(0.0, min(1.0, fraction)), 3)
            if message:
                j["message"] = message
            j["updated"] = time.time()

    def run() -> None:
        try:
            out = {"status": "done", "result": fn(progress), "progress": 1.0, "message": "Done"}
        except (ValueError, LLMError) as e:
            out = {"status": "error", "error": str(e)}
        except Exception:
            log.exception("job %s failed", key)
            out = {"status": "error", "error": "Something went wrong while processing this PDF."}
        with _lock:
            _jobs[jid].update(out, updated=time.time())

    _pool.submit(run)
    return jid


def get(jid: str) -> dict | None:
    with _lock:
        j = _jobs.get(jid)
        return None if j is None else {k: v for k, v in j.items() if k not in ("key", "updated")}
