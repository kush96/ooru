"""Offline tests never read the developer's .env or use real credentials."""

import pytest

from app.config import Settings, get_settings


@pytest.fixture
def clean_config(monkeypatch):
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings(clean_config, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    return get_settings()
