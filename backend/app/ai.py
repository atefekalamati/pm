"""The only place that talks to an AI service.

Any service with an OpenAI-compatible API works; three variables in `.env` choose it:

- `OPENROUTER_API_KEY`  the key (required; without it the AI is "not configured" and the rest of the app still works)
- `AI_BASE_URL`         default https://openrouter.ai/api/v1  (Google AI Studio: https://generativelanguage.googleapis.com/v1beta/openai/)
- `AI_MODEL`            default openai/gpt-oss-120b

The key is never logged, never returned and never put in an error message.
"""

import os
import time

import openai

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 60
RETRY_STATUSES = (429, 503)  # rate limit, busy service: worth one more try
RETRY_DELAY_SECONDS = 2.0


class AiNotConfigured(Exception):
    """No API key is set."""


class AiUnavailable(Exception):
    """The service could not be used. `status` is the HTTP status it answered, or None when it could not be reached."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def base_url() -> str:
    return os.environ.get("AI_BASE_URL", "").strip() or DEFAULT_BASE_URL


def model() -> str:
    return os.environ.get("AI_MODEL", "").strip() or DEFAULT_MODEL


def is_configured() -> bool:
    return bool(_key())


def _client() -> openai.OpenAI:
    if not is_configured():
        raise AiNotConfigured("AI is not configured")
    return openai.OpenAI(api_key=_key(), base_url=base_url(), timeout=TIMEOUT_SECONDS, max_retries=0)


def _safe(text: str) -> str:
    """Whatever comes back from the service is shortened, and the key is removed from it, before anyone sees it."""
    key = _key()
    return (text.replace(key, "<key>") if key else text)[:300]


def complete(messages: list[dict], response_format: dict | None = None) -> str:
    """Sends the conversation to the model and returns its answer as text.

    A rate limit (429) or a busy service (503) is tried once more after a short delay; anything else is not retried.
    """
    try:
        return _complete_once(messages, response_format)
    except AiUnavailable as error:
        if error.status not in RETRY_STATUSES:
            raise
    time.sleep(RETRY_DELAY_SECONDS)
    return _complete_once(messages, response_format)


def _complete_once(messages: list[dict], response_format: dict | None) -> str:
    extra = {"response_format": response_format} if response_format else {}
    try:
        response = _client().chat.completions.create(model=model(), messages=messages, **extra)
    except openai.APITimeoutError:
        raise AiUnavailable("The AI service did not answer in time") from None
    except openai.APIConnectionError:
        raise AiUnavailable("The AI service could not be reached") from None
    except openai.APIStatusError as error:
        raise AiUnavailable(f"The AI service answered {error.status_code}: {_safe(error.message)}", error.status_code) from None
    return response.choices[0].message.content or ""
