from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.chat.models.api.common.text_constraints import MessageText, ShortText


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Callers cannot supply system instructions or tool results.
    role: Literal["user", "assistant"]
    content: MessageText


class ChatLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ShortText


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: MessageText
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    location: ChatLocation | None = None

    @model_validator(mode="after")
    def limit_conversation_size(self):
        if len(self.message) + sum(len(item.content) for item in self.history) > 24000:
            raise ValueError("Message and history must total at most 24000 characters.")
        return self
