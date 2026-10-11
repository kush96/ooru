"""Inject fake clients/services without replacing module-level functions."""

import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.clients.llm import LLMClient
from app.dependencies import get_chat_service
from app.main import app
from app.modules.chat.chat_service import ChatService
from app.modules.chat.schemas import (
    AuthorityIntentResponse, ChatResponse, ModelReply,
)


def test_chat_service_uses_injected_client():
    client = Mock(spec=LLMClient)
    client.generate.return_value = ModelReply(answer="A local area.", suggested_questions=[])
    service = ChatService(llm_client=client)
    response = asyncio.run(service.answer_chat(message="What is a ward?"))
    assert response.answer == "A local area."
    assert response.sources == []
    client.generate.assert_awaited_once()
    assert client.generate.call_args.args[0][-1]["content"] == "What is a ward?"


def test_authority_tool_receives_services_injected_client():
    client = Mock(spec=LLMClient)
    expected = AuthorityIntentResponse(needs_authority_lookup=True, reason="Needs road authority guidance.")
    client.generate.return_value = expected
    service = ChatService(llm_client=client)
    response = asyncio.run(service.classify_authority_intent(prompt="Who repairs roads?"))
    assert response == expected
    client.generate.assert_awaited_once()
    assert client.generate.call_args.kwargs["response_model"] is AuthorityIntentResponse


def test_service_accepts_plain_context_without_mutating_history():
    client = Mock(spec=LLMClient)
    client.generate.return_value = ModelReply(answer="A local area.", suggested_questions=[])
    service = ChatService(llm_client=client)
    history = [{"role": "user", "content": "Hello"}]
    asyncio.run(service.answer_chat(
        message="What is a ward?", history=history, location_name="Indiranagar",
    ))
    messages = client.generate.call_args.args[0]
    assert messages[1] == history[0]
    assert '"name": "Indiranagar"' in messages[-1]["content"]
    assert messages[-1]["content"].endswith("What is a ward?")
    assert history == [{"role": "user", "content": "Hello"}]


def test_chat_dependency_wires_settings(settings):
    service = get_chat_service(settings)
    assert isinstance(service, ChatService)
    assert isinstance(service.llm_client, LLMClient)
    assert service.llm_client.settings is settings


@pytest.mark.parametrize("path, payload, method, result", [
    ("/api/chat", {"message": "Hello"}, "answer_chat",
     ChatResponse(answer="Injected answer.", suggested_questions=[])),
    ("/api/chat/authority-intent", {"prompt": "Who repairs roads?"}, "classify_authority_intent",
     AuthorityIntentResponse(needs_authority_lookup=True, reason="Injected decision.")),
])
def test_routes_accept_injected_service(settings, path, payload, method, result):
    service = Mock(spec=ChatService)
    handler = getattr(service, method)
    handler.return_value = result
    app.dependency_overrides[get_chat_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(path, json=payload)
        assert response.status_code == 200
        assert response.json() == result.model_dump()
        handler.assert_awaited_once()
        if method == "answer_chat":
            handler.assert_awaited_once_with(message="Hello", history=[], location_name=None)
        else:
            handler.assert_awaited_once_with(prompt="Who repairs roads?")
    finally:
        app.dependency_overrides.pop(get_chat_service)


def test_route_unpacks_history_and_location(settings):
    service = Mock(spec=ChatService)
    service.answer_chat.return_value = ChatResponse(answer="Hello.", suggested_questions=[])
    app.dependency_overrides[get_chat_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat", json={
                "message": " What is a ward? ",
                "history": [{"role": "user", "content": " Hello "}],
                "location": {"name": " Indiranagar "},
            })
        assert response.status_code == 200
        service.answer_chat.assert_awaited_once_with(
            message="What is a ward?",
            history=[{"role": "user", "content": "Hello"}],
            location_name="Indiranagar",
        )
    finally:
        app.dependency_overrides.pop(get_chat_service)
