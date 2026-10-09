"""Start with: uv run uvicorn app.main:app --reload --host 127.0.0.1"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.modules.chat.route import router as chat_router


# Use this backend's .env, not a file discovered in an unrelated working directory.
# Environment variables already set by the caller take precedence.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(title="Ooru API", version="0.1.0")
app.include_router(chat_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness only: does not contact a model or require the database."""
    return {"status": "ok"}
