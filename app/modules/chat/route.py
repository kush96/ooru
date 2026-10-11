"""HTTP endpoints. Chat workflows live in chat_service.py."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_chat_service
from app.modules.chat.schemas import (
    AuthorityIntentRequest, AuthorityIntentResponse, ChatRequest, ChatResponse,
)
from app.modules.chat.chat_service import ChatService


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    return await service.answer_chat(
        message=request.message,
        history=[item.model_dump() for item in request.history],
        location_name=request.location.name if request.location else None,
    )


@router.post("/authority-intent", response_model=AuthorityIntentResponse)
async def authority_intent(
    request: AuthorityIntentRequest, service: Annotated[ChatService, Depends(get_chat_service)],
) -> AuthorityIntentResponse:
    """Classify a prompt only. No authority lookup or document search yet."""
    return await service.classify_authority_intent(prompt=request.prompt)
