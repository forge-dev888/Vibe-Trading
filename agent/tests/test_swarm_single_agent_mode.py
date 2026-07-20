"""SWARM_SINGLE_AGENT_MODE: config plumbing + runtime enforcement.

Local-model (e.g. Ollama) users often can't serve multiple concurrent
requests reliably. This setting forces ``SwarmRuntime`` to run at most one
worker at a time, regardless of the ``max_workers`` value any caller passes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config.accessor import get_env_config, reset_env_config
from src.swarm.runtime import SwarmRuntime
from src.swarm.store import SwarmStore


@pytest.fixture(autouse=True)
def _reset_config():
    """Ensure each test starts from an unmodified EnvConfig singleton."""
    reset_env_config()
    yield
    reset_env_config()


def _make_runtime(tmp_path: Path, **kwargs) -> SwarmRuntime:
    store = SwarmStore(base_dir=tmp_path / "swarm_runs")
    return SwarmRuntime(store=store, **kwargs)


def test_swarm_single_agent_mode_defaults_to_false() -> None:
    assert get_env_config().swarm.swarm_single_agent_mode is False


def test_swarm_single_agent_mode_reads_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SWARM_SINGLE_AGENT_MODE", "true")
    reset_env_config()
    assert get_env_config().swarm.swarm_single_agent_mode is True


def test_runtime_respects_caller_max_workers_when_disabled(tmp_path: Path) -> None:
    """Default (disabled) behavior is unchanged: caller's value is used."""
    runtime = _make_runtime(tmp_path, max_workers=6)
    assert runtime._max_workers == 6


def test_runtime_forces_single_worker_when_enabled(monkeypatch, tmp_path: Path) -> None:
    """Enabling the setting overrides any max_workers passed by the caller."""
    monkeypatch.setenv("SWARM_SINGLE_AGENT_MODE", "true")
    reset_env_config()

    runtime = _make_runtime(tmp_path, max_workers=6)
    assert runtime._max_workers == 1


def test_runtime_forces_single_worker_with_default_max_workers(
    monkeypatch, tmp_path: Path,
) -> None:
    """Enabling the setting overrides the class default too."""
    monkeypatch.setenv("SWARM_SINGLE_AGENT_MODE", "true")
    reset_env_config()

    runtime = _make_runtime(tmp_path)
    assert runtime._max_workers == 1


def test_settings_ui_round_trip_controls_runtime_enforcement(
    monkeypatch, tmp_path: Path,
) -> None:
    """PUT /settings/llm toggling the checkbox actually gates SwarmRuntime.

    Exercises the same path the Settings UI checkbox drives: persist to
    .env -> reset_env_config() -> next SwarmRuntime() picks it up.
    """
    import api_server
    from fastapi.testclient import TestClient

    env_example = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    env_example.write_text(
        "LANGCHAIN_PROVIDER=openrouter\n"
        "LANGCHAIN_MODEL_NAME=deepseek/deepseek-v4-pro\n"
        "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1\n"
        "OPENROUTER_API_KEY=sk-or-v1-your-key-here\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_server, "ENV_PATH", env_path)
    monkeypatch.setattr(api_server, "LEGACY_ENV_PATH", tmp_path / "legacy" / ".env", raising=False)
    monkeypatch.setattr(api_server, "ENV_EXAMPLE_PATH", env_example)
    monkeypatch.setattr(api_server, "_baostock_supported", lambda: False)
    monkeypatch.setattr(api_server, "_baostock_installed", lambda: False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)

    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.put(
        "/settings/llm",
        json={
            "provider": "openrouter",
            "model_name": "deepseek/deepseek-v4-pro",
            "base_url": "https://openrouter.ai/api/v1",
            "temperature": 0.1,
            "timeout_seconds": 45,
            "max_retries": 1,
            "reasoning_effort": "",
            "swarm_single_agent_mode": True,
        },
    )
    assert response.status_code == 200

    runtime = _make_runtime(tmp_path, max_workers=6)
    assert runtime._max_workers == 1
