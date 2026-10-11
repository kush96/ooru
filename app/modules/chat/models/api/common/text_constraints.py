"""Shared text validation constraints for chat API requests and responses."""

from typing import Annotated

from pydantic import StringConstraints


MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
