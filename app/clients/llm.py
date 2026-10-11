"""Model API access. Groq today; an OpenAI-compatible server can replace it."""

from typing import TypeVar

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings


Result = TypeVar("Result", bound=BaseModel)


class InferenceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(
        self,
        messages: list[dict[str, str]],
        response_model: type[Result],
    ) -> Result:
        """Make one model call and parse its JSON into the requested Pydantic model."""
        settings = self.settings
        api_key = settings.llm_api_key.get_secret_value().strip()
        if settings.is_groq:
            api_key = api_key or settings.groq_api_key.get_secret_value().strip()
            if not api_key:
                raise InferenceError(503, "Set GROQ_API_KEY in the backend .env, then restart.")

        # Strict JSON schemas on Groq; json_object is an opt-in fallback for local servers.
        response_format = {"type": settings.llm_json_mode}
        if settings.llm_json_mode == "json_schema":
            response_format["json_schema"] = {
                "name": response_model.__name__,
                "strict": True,
                "schema": response_model.model_json_schema(),
            }

        options = {}
        if settings.is_groq and settings.llm_model.startswith("openai/gpt-oss-"):
            options["reasoning_effort"] = "low"

        try:
            # Never forward a Groq key to a different host. Local servers may ignore auth.
            async with AsyncOpenAI(
                base_url=str(settings.llm_base_url),
                api_key=api_key or "local",
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            ) as client:
                completion = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=messages,
                    response_format=response_format,
                    max_tokens=settings.llm_max_tokens,
                    **options,
                )
        except APITimeoutError as error:
            raise InferenceError(504, "The model took too long to respond. Please try again.") from error
        except APIConnectionError as error:
            raise InferenceError(503, "Cannot reach the model provider. Please try later.") from error
        except APIStatusError as error:
            status = 503 if error.status_code in {401, 403, 429} else 502
            raise InferenceError(status, "Model request failed. Check credentials, model access and provider limits.") from error
        except APIError as error:
            raise InferenceError(502, "The model provider returned an invalid response.") from error

        if not completion.choices or completion.choices[0].finish_reason != "stop":
            raise InferenceError(502, "The model did not return a complete answer. Please try again.")
        content = completion.choices[0].message.content
        if not content:
            raise InferenceError(502, "The model returned no answer. Please try again.")
        try:
            return response_model.model_validate_json(content)
        except ValidationError as error:
            raise InferenceError(502, "The model returned an invalid response. Please try again.") from error
