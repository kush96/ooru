"""Start with: uv run uvicorn app.main:app --reload --host 127.0.0.1"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.clients.llm import InferenceError
from app.config import get_settings
from app.modules.chat.route import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # Validate settings at startup, without contacting external service.
    yield


app = FastAPI(title="Ooru API", version="0.1.0", lifespan=lifespan)
app.include_router(chat_router)


@app.exception_handler(InferenceError)
async def handle_inference_error(request: Request, error: InferenceError) -> JSONResponse:
    # Only our safe messages reach the caller, never provider error bodies or keys.
    return JSONResponse(status_code=error.status_code, content={"detail": error.message})


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness only: does not contact a model or require the database."""
    return {"status": "ok"}
