import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_env(path: Path) -> None:
    """Tiny .env reader (KEY=value lines). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Settings:
    # LLM (OpenRouter, OpenAI-compatible API)
    openrouter_api_key: str = _env("OPENROUTER_API_KEY", "")
    llm_base_url: str = _env("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    llm_model: str = _env("LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    llm_max_tokens: int = int(_env("LLM_MAX_TOKENS", "3000"))
    llm_disable_reasoning: bool = _env("LLM_DISABLE_REASONING", "true").lower() == "true"

    # Retrieval
    embed_model: str = _env("EMBED_MODEL", "intfloat/multilingual-e5-base")
    chunk_size: int = 800
    chunk_overlap: int = 100
    top_k: int = 6
    candidates: int = 20  # per retriever (dense and BM25) before fusion

    # PDF limits
    max_upload_mb: int = int(_env("MAX_UPLOAD_MB", "25"))
    max_pages: int = int(_env("MAX_PAGES", "300"))

    # Summary budget
    digest_chars_per_page: int = int(_env("DIGEST_CHARS_PER_PAGE", "1400"))
    batch_chars: int = int(_env("BATCH_CHARS", "40000"))
    full_text_summary_max_chars: int = int(_env("FULL_TEXT_SUMMARY_MAX_CHARS", "80000"))

    # Storage
    data_dir: Path = Path(_env("DATA_DIR", str(ROOT / "data")))
    doc_ttl_hours: int = int(_env("DOC_TTL_HOURS", "0"))


settings = Settings()
