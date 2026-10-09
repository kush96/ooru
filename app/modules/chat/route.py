"""HTTP handling only. Model inference lives in service.py."""

from fastapi import APIRouter, HTTPException

from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.modules.chat.service import ChatServiceError, answer_chat


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        return await answer_chat(request)
    except ChatServiceError as error:
        # Only our own safe messages are exposed, never provider error bodies.
        raise HTTPException(status_code=error.status_code, detail=error.message) from error
