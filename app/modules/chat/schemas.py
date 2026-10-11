"""The JSON accepted and returned by the chat endpoint."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictBool, StringConstraints, model_validator


MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


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


class Source(BaseModel):
    id: ShortText
    title: ShortText
    url: HttpUrl


class ModelReply(BaseModel):
    """Only these fields come from the model; sources must come from retrieval."""

    model_config = ConfigDict(extra="forbid")

    answer: AnswerText
    suggested_questions: list[ShortText] = Field(max_length=3)


class ChatResponse(ModelReply):
    # This first version has no retrieval, database tools or live web search.
    mode: Literal["model_only"] = "model_only"
    sources: list[Source] = Field(default_factory=list)


class AuthorityIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: MessageText


class AuthorityIntentResponse(BaseModel):
    """An intent decision, not an authority lookup or a document-search result."""

    model_config = ConfigDict(extra="forbid")

    needs_authority_lookup: StrictBool
    reason: ShortText
