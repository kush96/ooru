from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ModelReply(BaseModel):
    """Only these fields come from the model; sources must come from retrieval."""

    model_config = ConfigDict(extra="forbid")

    answer: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000),
    ]
    suggested_questions: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    ] = Field(max_length=3)
