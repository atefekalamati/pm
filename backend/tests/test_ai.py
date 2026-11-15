"""The AI connection. Every test uses a fake client, except the last one: the single real 2+2 call, which runs only when a key exists."""

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

from app import ai

KEY = "test-key-0123456789-not-a-real-key"
REQUEST = httpx.Request("POST", "https://example.test/v1/chat/completions")


class FakeClient:
    """Stands in for openai.OpenAI. Records what it was asked and answers or fails as told."""

    def __init__(self, answer: str | None = "4", error: Exception | None = None):
        self.calls: list[dict] = []
        self._answer, self._error = answer, error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._answer))])


def status_error(status: int, message: str = "nope") -> openai.APIStatusError:
    return openai.APIStatusError(message, response=httpx.Response(status, request=REQUEST), body=None)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)


def use(monkeypatch, client: FakeClient) -> FakeClient:
    monkeypatch.setattr(ai, "_client", lambda: client)
    return client


# ---- settings --------------------------------------------------------------------------------------


def test_defaults_are_openrouter_and_gpt_oss():
    assert ai.base_url() == "https://openrouter.ai/api/v1"
    assert ai.model() == "openai/gpt-oss-120b"
    assert ai.is_configured() is False


def test_the_three_variables_choose_the_service(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setenv("AI_MODEL", "gemini-3.8-flash")
    assert (ai.base_url(), ai.model(), ai.is_configured()) == ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.8-flash", True)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_fall_back_to_the_defaults(monkeypatch, blank):
    monkeypatch.setenv("AI_BASE_URL", blank)
    monkeypatch.setenv("AI_MODEL", blank)
    monkeypatch.setenv("OPENROUTER_API_KEY", blank)
    assert (ai.base_url(), ai.model(), ai.is_configured()) == (ai.DEFAULT_BASE_URL, ai.DEFAULT_MODEL, False)


def test_the_client_is_built_from_the_settings(monkeypatch, configured):
    seen = {}

    class Capture:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(ai.openai, "OpenAI", Capture)
    monkeypatch.setenv("AI_BASE_URL", "https://other.test/v1")
    ai._client()
    assert seen["api_key"] == KEY and seen["base_url"] == "https://other.test/v1" and seen["timeout"] == ai.TIMEOUT_SECONDS


# ---- complete() ------------------------------------------------------------------------------------


def test_complete_sends_the_model_and_the_conversation_and_returns_the_text(monkeypatch, configured):
    monkeypatch.setenv("AI_MODEL", "some-model")
    client = use(monkeypatch, FakeClient(answer="four"))
    messages = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "2+2?"}]
    assert ai.complete(messages) == "four"
    assert client.calls == [{"model": "some-model", "messages": messages}]


def test_complete_passes_a_response_format(monkeypatch, configured):
    client = use(monkeypatch, FakeClient())
    schema = {"type": "json_object"}
    ai.complete([{"role": "user", "content": "x"}], response_format=schema)
    assert client.calls[0]["response_format"] == schema


def test_an_empty_answer_is_an_empty_string(monkeypatch, configured):
    use(monkeypatch, FakeClient(answer=None))
    assert ai.complete([{"role": "user", "content": "x"}]) == ""


def test_without_a_key_nothing_is_sent():
    with pytest.raises(ai.AiNotConfigured, match="AI is not configured"):
        ai.complete([{"role": "user", "content": "x"}])


@pytest.mark.parametrize(
    ("error", "status", "words"),
    [
        (openai.APITimeoutError(request=REQUEST), None, "in time"),
        (openai.APIConnectionError(request=REQUEST), None, "could not be reached"),
        (status_error(401, "API key not valid"), 401, "401: API key not valid"),
        (status_error(403, "User location is not supported"), 403, "403: User location is not supported"),
        (status_error(404, "model not found"), 404, "404: model not found"),
        (status_error(429, "quota"), 429, "429: quota"),
        (status_error(500, "oops"), 500, "500: oops"),
    ],
)
def test_service_problems_become_one_clear_error(monkeypatch, configured, error, status, words):
    use(monkeypatch, FakeClient(error=error))
    with pytest.raises(ai.AiUnavailable) as caught:
        ai.complete([{"role": "user", "content": "x"}])
    assert caught.value.status == status
    assert words in str(caught.value)


def test_the_key_is_removed_from_whatever_the_service_says_and_it_is_shortened(monkeypatch, configured):
    use(monkeypatch, FakeClient(error=status_error(400, f"bad key {KEY} " + "x" * 1000)))
    with pytest.raises(ai.AiUnavailable) as caught:
        ai.complete([{"role": "user", "content": "x"}])
    assert KEY not in str(caught.value) and "<key>" in str(caught.value)
    assert len(str(caught.value)) < 400


# ---- the endpoints ---------------------------------------------------------------------------------


def test_status_says_whether_a_key_is_set(me, monkeypatch):
    assert me.get("/api/ai/status").json() == {"configured": False}
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    assert me.get("/api/ai/status").json() == {"configured": True}
    assert KEY not in me.get("/api/ai/status").text


def test_without_a_key_the_test_says_so_and_the_rest_of_the_app_works(me):
    response = me.post("/api/ai/test")
    assert response.status_code == 503 and response.json() == {"detail": "AI is not configured"}
    assert me.get("/api/board").status_code == 200
    assert me.post("/api/cards", json={"columnId": "todo", "title": "Still works"}).status_code == 201
    assert me.post("/api/spaces/general/messages", json={"text": "and chat"}).status_code == 201
    assert me.get("/api/health").status_code == 200


def test_the_two_plus_two_endpoint_returns_the_models_answer(me, monkeypatch, configured):
    monkeypatch.setenv("AI_MODEL", "gemini-3.8-flash")
    client = use(monkeypatch, FakeClient(answer=" 4\n"))
    response = me.post("/api/ai/test")
    assert response.status_code == 200
    assert response.json() == {"question": "What is 2+2? Answer with just the number.", "answer": "4", "model": "gemini-3.8-flash"}
    assert client.calls[0]["messages"][0]["content"].startswith("What is 2+2?")


def test_a_service_failure_is_a_502_with_the_reason(me, monkeypatch, configured):
    use(monkeypatch, FakeClient(error=status_error(403, "User location is not supported for the API use.")))
    response = me.post("/api/ai/test")
    assert response.status_code == 502
    assert "403" in response.json()["detail"] and "User location is not supported" in response.json()["detail"]


def test_an_unreachable_service_is_a_502(me, monkeypatch, configured):
    use(monkeypatch, FakeClient(error=openai.APIConnectionError(request=REQUEST)))
    response = me.post("/api/ai/test")
    assert response.status_code == 502 and "could not be reached" in response.json()["detail"]


def test_the_key_never_appears_in_any_answer(me, monkeypatch, configured):
    use(monkeypatch, FakeClient(error=status_error(401, f"Incorrect API key provided: {KEY}")))
    for response in (me.post("/api/ai/test"), me.get("/api/ai/status")):
        assert KEY not in response.text and KEY not in str(response.headers)
    use(monkeypatch, FakeClient(answer="4"))
    assert KEY not in me.post("/api/ai/test").text


def test_the_key_never_appears_in_the_logs(me, monkeypatch, configured, caplog):
    use(monkeypatch, FakeClient(error=status_error(401, f"Incorrect API key provided: {KEY}")))
    with caplog.at_level("DEBUG"):
        me.post("/api/ai/test")
        me.get("/api/ai/status")
    assert KEY not in caplog.text


def test_the_ai_routes_need_sign_in(client, monkeypatch, configured):
    use(monkeypatch, FakeClient())
    assert client.get("/api/ai/status").status_code == 401
    assert client.post("/api/ai/test").status_code == 401


def test_the_key_is_not_in_the_api_description_either(me, configured):
    assert KEY not in me.get("/openapi.json").text


# ---- the one real call -----------------------------------------------------------------------------


def _real_settings() -> dict[str, str]:
    """The key and service of this machine: from the environment, else from the .env file in the project root."""
    found = {n: os.environ[n] for n in ("OPENROUTER_API_KEY", "AI_BASE_URL", "AI_MODEL") if os.environ.get(n)}
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if "OPENROUTER_API_KEY" not in found and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() in ("OPENROUTER_API_KEY", "AI_BASE_URL", "AI_MODEL") and value.strip():
                found[name.strip()] = value.strip().strip('"').strip("'")
    return found


@pytest.mark.skipif(not _real_settings().get("OPENROUTER_API_KEY"), reason="no OPENROUTER_API_KEY: the only test that calls a real service is skipped")
def test_the_real_service_answers_2_plus_2(me, monkeypatch):
    """The only test that reaches a real service, and only when a key exists. Never prints the key."""
    for name, value in _real_settings().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ai, "TIMEOUT_SECONDS", 20)  # do not wait a minute for a busy service
    response = me.post("/api/ai/test")
    reason = str(response.json().get("detail"))  # the service's reason, never the key
    if response.status_code == 502 and ("answered 503" in reason or "in time" in reason):
        # Busy or overloaded on the service's side (seen with the newest Gemini models): not a problem of ours, so not a failure.
        # A wrong key, a wrong model name or a blocked location (401, 403, 404) still fails below.
        pytest.skip(f"the real service is busy right now: {reason}")
    assert response.status_code == 200, f"{response.status_code}: {reason}"
    assert "4" in response.json()["answer"]
    assert response.json()["model"] == ai.model()
