from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from app.modules.chat.models.api.common.text_constraints import ShortText
from app.modules.chat.models.model_reply import ModelReply


class Source(BaseModel):
    id: ShortText
    title: ShortText
    url: HttpUrl


class ChatResponse(ModelReply):
    # This first version has no retrieval, database tools or live web search.
    mode: Literal["model_only"] = "model_only"
    sources: list[Source] = Field(default_factory=list)
