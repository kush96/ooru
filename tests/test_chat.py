"""Exercise the real route/service with a fake provider; no API key or network needed."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from groq import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError

from app.main import app
from app.modules.chat import service


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
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
    monkeypatch.setattr(service, "AsyncGroq", lambda **kwargs: context)
    return create


def test_health_without_model_config(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
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
    assert kwargs["model"] == "test-model"
    assert kwargs["response_format"] == {"type": "json_object"}
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


@pytest.mark.parametrize("name", ["GROQ_API_KEY", "GROQ_MODEL"])
def test_missing_configuration(client, provider, monkeypatch, name):
    monkeypatch.delenv(name, raising=False)
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
    response = httpx.Response(500, request=request)
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
