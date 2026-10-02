"""Talk to a chat LLM through any OpenAI-compatible API (we use Groq).

Only this file knows about the LLM provider. To switch provider, change
LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env - no code change needed.
"""
import logging
from typing import Optional

import httpx

from app import config

log = logging.getLogger("kjs.llm")


class LLMError(Exception):
    """The LLM could not give an answer (not set up, busy, timeout, bad reply)."""


_client: Optional[httpx.Client] = None


def set_client(client: Optional[httpx.Client]) -> None:
    """Tests plug in a fake HTTP client here."""
    global _client
    _client = client


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=config.LLM_TIMEOUT_SECONDS)
    return _client


def is_configured() -> bool:
    return bool(config.LLM_API_KEY and config.LLM_MODEL and config.LLM_BASE_URL)


def chat(messages: list[dict], max_tokens: int = 1200, temperature: float = 0.2) -> str:
    """Send the conversation, return the model's reply text. Raises LLMError."""
    if not is_configured():
        raise LLMError("AI answers are not set up")
    payload = {"model": config.LLM_MODEL, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if config.LLM_REASONING_EFFORT:
        payload["reasoning_effort"] = config.LLM_REASONING_EFFORT
    try:
        response = _http().post(f"{config.LLM_BASE_URL}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"})
    except httpx.HTTPError as error:
        raise LLMError(f"could not reach the AI service ({type(error).__name__})") from error

    if response.status_code == 429:
        raise LLMError("the AI service is busy (rate limit)")
    if response.status_code != 200:
        # the body can help debugging, but it is only logged on the server, never sent to users
        log.warning("LLM error %s: %s", response.status_code, response.text[:500])
        raise LLMError(f"the AI service returned an error ({response.status_code})")
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise LLMError("the AI service sent an unexpected reply") from error
    if not content or not content.strip():
        raise LLMError("the AI service sent an empty reply")
    return content.strip()
