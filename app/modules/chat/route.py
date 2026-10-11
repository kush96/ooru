"""HTTP endpoints. Chat workflows live in chat_service.py."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.chat.models.api.request.authority_intent_request import AuthorityIntentRequest
from app.modules.chat.models.api.request.chat_request import ChatRequest
from app.modules.chat.models.api.response.authority_intent_response import AuthorityIntentResponse
from app.modules.chat.models.api.response.chat_response import ChatResponse
from app.modules.chat.service.chat_service import ChatService


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest, service: Annotated[ChatService, Depends(ChatService)],
) -> ChatResponse:
    return await service.answer_chat(
        message=request.message,
        history=[item.model_dump() for item in request.history],
        location_name=request.location.name if request.location else None,
    )


@router.post("/authority-intent", response_model=AuthorityIntentResponse)
async def authority_intent(
    request: AuthorityIntentRequest, service: Annotated[ChatService, Depends(ChatService)],
) -> AuthorityIntentResponse:
    """Classify a prompt only. No authority lookup or document search yet."""
    return await service.classify_authority_intent(prompt=request.prompt)
