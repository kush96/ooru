"""Settings loading and validation, without contacting a database or model."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import app


def test_defaults_and_optional_credentials(clean_config):
    settings = get_settings()
    assert settings.is_groq
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.llm_json_mode == "json_schema"
    assert settings.llm_max_tokens == 2048
    assert settings.llm_timeout_seconds == 30.0
    assert settings.groq_api_key.get_secret_value() == ""
    assert settings.database_url.get_secret_value() == ""
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_dotenv_environment_precedence_and_secret_masking(clean_config, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GROQ_API_KEY=file-key-not-real\n"
        "LLM_MODEL=file-model\n"
        "LLM_MAX_TOKENS=1024\n"
        "DATABASE_URL=postgresql://user:fake-password@localhost/example\n"
        "POSTGRES_DB=example\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODEL", "environment-model")
    settings = Settings(_env_file=env_file)
    assert settings.llm_model == "environment-model"
    assert settings.llm_max_tokens == 1024
    assert settings.groq_api_key.get_secret_value() == "file-key-not-real"
    assert "file-key-not-real" not in repr(settings)
    assert "fake-password" not in settings.model_dump_json()
    assert "GROQ_API_KEY" not in os.environ  # Reading .env does not mutate the process.


def test_dotenv_path_is_backend_relative(monkeypatch, tmp_path):
    env_path = Settings.model_config["env_file"]
    monkeypatch.chdir(tmp_path)
    assert env_path.is_absolute()
    assert env_path == Path(__file__).resolve().parents[1] / ".env"


def test_settings_are_loaded_once(clean_config, monkeypatch):
    first = get_settings()
    monkeypatch.setenv("LLM_MODEL", "changed-after-startup")
    assert get_settings() is first
    assert first.llm_model == "openai/gpt-oss-120b"
    get_settings.cache_clear()  # A fresh process would reload the configuration.
    assert get_settings().llm_model == "changed-after-startup"


@pytest.mark.parametrize("name, value", [
    ("LLM_JSON_MODE", "typo"),
    ("LLM_BASE_URL", "not-a-url"),
    ("LLM_BASE_URL", "ftp://localhost/model"),
    ("LLM_MODEL", "  "),
    ("LLM_TIMEOUT_SECONDS", "0"),
    ("LLM_TIMEOUT_SECONDS", "nan"),
    ("LLM_MAX_TOKENS", "-1"),
    ("LLM_MAX_TOKENS", "not-a-number"),
])
def test_invalid_config_prevents_startup(clean_config, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        with TestClient(app):
            pass


def test_custom_server_requires_explicit_model(clean_config, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    with pytest.raises(ValidationError, match="Set LLM_MODEL"):
        get_settings()
    monkeypatch.setenv("LLM_MODEL", "local-model")
    assert not get_settings().is_groq


def test_validation_errors_hide_input_values(clean_config, monkeypatch):
    monkeypatch.setenv("LLM_JSON_MODE", "secret-accidentally-pasted-here")
    with pytest.raises(ValidationError) as error:
        get_settings()
    assert "secret-accidentally-pasted-here" not in str(error.value)
