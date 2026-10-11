"""Check the real SDK's HTTP request without contacting a model server."""

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.clients import llm
from app.config import get_settings
from app.modules.chat.models.api.response.authority_intent_response import AuthorityIntentResponse


@pytest.mark.parametrize("local", [False, True])
def test_openai_compatible_request(clean_config, monkeypatch, local):
    base_url = "http://127.0.0.1:11434/v1" if local else "https://api.groq.com/openai/v1"
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    monkeypatch.setenv("LLM_MODEL", "local-model" if local else "openai/gpt-oss-120b")
    monkeypatch.setenv("LLM_JSON_MODE", "json_object" if local else "json_schema")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "test-completion",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps({
                    "needs_authority_lookup": True,
                    "reason": "The user wants the department responsible for a public road.",
                })},
            }],
        })

    def make_client(**kwargs):
        return AsyncOpenAI(http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)), **kwargs)

    monkeypatch.setattr(llm, "AsyncOpenAI", make_client)
    client = llm.LLMClient(get_settings())
    result = asyncio.run(client.generate(
        [{"role": "user", "content": "Return JSON: who maintains this road?"}],
        AuthorityIntentResponse,
    ))
    assert result.needs_authority_lookup is True
    assert len(requests) == 1
    assert str(requests[0].url) == f"{base_url}/chat/completions"
    expected_key = "local" if local else "test-groq-key"
    assert requests[0].headers["authorization"] == f"Bearer {expected_key}"
    body = json.loads(requests[0].content)
    assert body["max_tokens"] == 2048
    assert body["response_format"]["type"] == ("json_object" if local else "json_schema")
