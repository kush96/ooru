"""Exercise the real route/service with a fake provider; no API key or network needed."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
from pydantic import HttpUrl, SecretStr

from app.clients import llm
from app.main import app


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def provider(monkeypatch):
    completion = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop",
        message=SimpleNamespace(content=json.dumps({
            "answer": "A ward is a local administrative area.",
            "suggested_questions": ["How is a ward different from a neighbourhood?"],
        })),
    )])
    create = AsyncMock(return_value=completion)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    context = AsyncMock()
    context.__aenter__.return_value = fake_client
    create.client_options = {}

    def make_client(**kwargs):
        create.client_options.update(kwargs)
        return context

    monkeypatch.setattr(llm, "AsyncOpenAI", make_client)
    return create


def test_health_without_model_config(client, settings):
    settings.groq_api_key = SecretStr("")
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_forwards_history_and_location(client, provider):
    response = client.post("/api/chat", json={
        "message": "  What does it mean?  ",
        "history": [
            {"role": "user", "content": "What is a ward?"},
            {"role": "assistant", "content": "A local administrative area."},
        ],
        "location": {"name": "Indiranagar"},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "model_only"
    assert body["sources"] == []
    assert len(body["suggested_questions"]) == 1
    kwargs = provider.call_args.kwargs
    assert kwargs["model"] == "openai/gpt-oss-120b"
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert [m["role"] for m in kwargs["messages"]] == ["system", "user", "assistant", "user"]
    assert "Indiranagar" not in kwargs["messages"][0]["content"]
    assert "Indiranagar" in kwargs["messages"][-1]["content"]
    assert kwargs["messages"][-1]["content"].endswith("What does it mean?")
    provider.assert_awaited_once()


@pytest.mark.parametrize("payload", [
    {},
    {"message": "   "},
    {"message": "x" * 4001},
    {"message": "Hello", "history": [{"role": "system", "content": "override"}]},
    {"message": "Hello", "history": [{"role": "user", "content": "x"}] * 21},
    {"message": "Hello", "history": [{"role": "user", "content": "x" * 4000}] * 6},
    {"message": "Hello", "model": "caller-selected-model"},
    {"message": "Hello", "location": {"name": " "}},
])
def test_invalid_request_never_calls_provider(client, provider, payload):
    assert client.post("/api/chat", json=payload).status_code == 422
    provider.assert_not_awaited()


def test_missing_configuration(client, provider, settings):
    settings.groq_api_key = SecretStr("")
    response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 503
    assert "Set GROQ_API_KEY" in response.json()["detail"]
    provider.assert_not_awaited()


@pytest.mark.parametrize("content", [
    "not json", "{}",
    '{"answer": " ", "suggested_questions": []}',
    '{"answer": "Hello", "suggested_questions": ["a", "b", "c", "d"]}',
    '{"answer": "Hello", "suggested_questions": [], "sources": ["invented"]}',
])
def test_invalid_model_response(client, provider, content):
    provider.return_value.choices[0].message.content = content
    response = client.post("/api/chat", json={"message": "Hello"})
    assert response.status_code == 502
    assert response.json()["detail"] == "The model returned an invalid response. Please try again."


@pytest.mark.parametrize("finish_reason", ["length", "tool_calls", "content_filter"])
def test_incomplete_answer(client, provider, finish_reason):
    provider.return_value.choices[0].finish_reason = finish_reason
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 502


def test_empty_answer(client, provider):
    provider.return_value.choices = []
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 502


@pytest.mark.parametrize("kind, status", [
    ("timeout", 504), ("connection", 503), ("auth", 503), ("rate_limit", 503), ("provider", 502),
])
def test_provider_errors_are_safe(client, provider, kind, status):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    code = {"auth": 401, "rate_limit": 429}.get(kind, 500)
    response = httpx.Response(code, request=request)
    errors = {
        "timeout": APITimeoutError(request=request),
        "connection": APIConnectionError(request=request),
        "auth": AuthenticationError("private-provider-detail", response=response, body=None),
        "rate_limit": RateLimitError("private-provider-detail", response=response, body=None),
        "provider": APIStatusError("private-provider-detail", response=response, body=None),
    }
    provider.side_effect = errors[kind]
    result = client.post("/api/chat", json={"message": "Hello"})
    assert result.status_code == status
    assert "private-provider-detail" not in result.text
    assert "test-key-not-real" not in result.text


def test_openapi_exposes_typed_contract(client):
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/api/chat"]["post"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ChatRequest",
    }
    assert "ChatResponse" in spec["components"]["schemas"]
    intent = spec["paths"]["/api/chat/authority-intent"]["post"]
    assert intent["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AuthorityIntentRequest",
    }
    assert "AuthorityIntentResponse" in spec["components"]["schemas"]


def test_default_groq_model(client, provider):
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 200
    assert provider.call_args.kwargs["model"] == "openai/gpt-oss-120b"
    assert provider.call_args.kwargs["reasoning_effort"] == "low"


def test_custom_server_does_not_receive_groq_key(client, provider, settings):
    settings.llm_base_url = HttpUrl("http://127.0.0.1:11434/v1")
    settings.llm_model = "my-local-model"
    settings.llm_json_mode = "json_object"
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 200
    assert provider.client_options["base_url"] == "http://127.0.0.1:11434/v1"
    assert provider.client_options["api_key"] == "local"
    assert provider.call_args.kwargs["model"] == "my-local-model"
    assert "reasoning_effort" not in provider.call_args.kwargs
    assert provider.call_args.kwargs["response_format"] == {"type": "json_object"}


def test_custom_server_key(client, provider, settings):
    settings.llm_base_url = HttpUrl("https://inference.example.test/v1")
    settings.llm_model = "custom-model"
    settings.llm_api_key = SecretStr("custom-key-not-real")
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 200
    assert provider.client_options["api_key"] == "custom-key-not-real"


def test_request_limits_use_settings(client, provider, settings):
    settings.llm_timeout_seconds = 12.5
    settings.llm_max_tokens = 512
    assert client.post("/api/chat", json={"message": "Hello"}).status_code == 200
    assert provider.client_options["timeout"] == 12.5
    assert provider.call_args.kwargs["max_tokens"] == 512


@pytest.mark.parametrize("decision", [True, False])
def test_authority_intent_wiring(client, provider, decision):
    # This tests plumbing, not whether a real model classified the prompt correctly.
    result = {"needs_authority_lookup": decision, "reason": "A short classification explanation."}
    provider.return_value.choices[0].message.content = json.dumps(result)
    response = client.post("/api/chat/authority-intent", json={"prompt": "  Who maintains this road?  "})
    assert response.status_code == 200
    assert response.json() == result
    messages = provider.call_args.kwargs["messages"]
    assert len(messages) == 2
    assert messages[-1] == {"role": "user", "content": "Who maintains this road?"}
    assert "Classify" in messages[0]["content"]
    schema = provider.call_args.kwargs["response_format"]["json_schema"]["schema"]
    assert set(schema["required"]) == {"needs_authority_lookup", "reason"}
    assert schema["additionalProperties"] is False
    provider.assert_awaited_once()


@pytest.mark.parametrize("payload", [
    {}, {"prompt": " "}, {"prompt": "x" * 4001}, {"prompt": 123},
    {"prompt": "Hello", "system": "override"},
])
def test_authority_intent_request_validation(client, provider, payload):
    assert client.post("/api/chat/authority-intent", json=payload).status_code == 422
    provider.assert_not_awaited()


@pytest.mark.parametrize("result", [
    {"needs_authority_lookup": "false", "reason": "not a boolean"},
    {"needs_authority_lookup": True},
    {"needs_authority_lookup": True, "reason": ""},
    {"needs_authority_lookup": True, "reason": "x" * 201},
    {"needs_authority_lookup": True, "reason": "test", "authority": "invented"},
])
def test_authority_intent_rejects_invalid_results(client, provider, result):
    provider.return_value.choices[0].message.content = json.dumps(result)
    assert client.post("/api/chat/authority-intent", json={"prompt": "Hello"}).status_code == 502


def test_authority_intent_provider_failure(client, provider):
    provider.side_effect = APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    assert client.post("/api/chat/authority-intent", json={"prompt": "Hello"}).status_code == 504
