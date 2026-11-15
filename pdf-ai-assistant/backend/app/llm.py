"""LLM client for OpenRouter (Nemotron 3 Ultra free by default)."""
import threading
import time

from .config import settings


class LLMError(Exception):
    """Message is safe to show to the user."""


_client = None
_lock = threading.Lock()


def _get_client():
    global _client
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY is not set. Add it to the .env file and restart the server.")
    with _lock:
        if _client is None:
            from openai import OpenAI

            _client = OpenAI(
                api_key=settings.openrouter_api_key,
                base_url=settings.llm_base_url,
                timeout=120,
                max_retries=0,
                default_headers={"X-Title": "PDF AI Assistant"},
            )
        return _client


def chat(prompt: str, *, system: str | None = None, max_tokens: int | None = None,
         temperature: float = 0.2) -> str:
    from openai import APIConnectionError, APIStatusError, BadRequestError

    client = _get_client()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    kwargs = dict(
        model=settings.llm_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens or settings.llm_max_tokens,
    )
    reasoning_off = settings.llm_disable_reasoning
    delay = 8
    for attempt in range(5):
        extra = {"extra_body": {"reasoning": {"enabled": False}}} if reasoning_off else {}
        try:
            resp = client.chat.completions.create(**kwargs, **extra)
            choices = resp.choices or []
            text = ((choices[0].message.content if choices else "") or "").strip()
            if not text:
                raise LLMError("The model returned an empty answer. Try again.")
            return text
        except BadRequestError as e:
            if reasoning_off:  # this provider may not accept the reasoning switch
                reasoning_off = False
                continue
            raise LLMError(f"The model rejected the request: {str(e)[:160]}")
        except APIStatusError as e:
            if e.status_code == 401:
                raise LLMError("OpenRouter rejected the API key.")
            if e.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            if e.status_code == 429:
                raise LLMError("The free model is rate limited right now. Wait a minute and try again.")
            raise LLMError(f"Language model error ({e.status_code}).")
        except APIConnectionError:
            if attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            raise LLMError("Could not reach the language model service.")
    raise LLMError("The language model did not respond. Try again.")
