"""Isolated probe worker, synthetic fourth provider, and secret-canary tests."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from sase.llm_provider.usage.probe import (
    default_probe_context,
    probe_in_process,
    run_usage_probe,
    worker_environ,
)
from sase.testing.usage_synthetic import (
    SECRET_CANARY,
    SYNTHETIC_MODE_ENV,
    SYNTHETIC_PIDFILE_ENV,
    SYNTHETIC_PLUGIN_SPEC,
    _SyntheticUsageProvider,
)
from sase.llm_provider.usage.types import validate_observation


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_synthetic_fourth_provider_collects_without_core_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    context = default_probe_context("synth", deadline_seconds=20)
    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
    )
    assert result.skipped is None
    assert result.observation is not None
    assert result.observation["provider"] == "synth"
    assert result.observation["outcome"] == "ok"
    assert result.observation["windows"][0]["key"] == "week"
    validate_observation(result.observation, now=context.request_started_at + 5)


def test_in_process_synthetic_probe_matches_isolated_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    context = default_probe_context("synth", now=1_800_000_000.0)
    result = run_usage_probe(
        context,
        isolate=False,
        plugin=_SyntheticUsageProvider(),
        now=1_800_000_000.0,
    )
    assert result.observation is not None
    assert result.observation["windows"][0]["used_percent"] == 12.5


def test_hanging_plugin_is_killed_at_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    context = default_probe_context("synth", deadline_seconds=1.5)
    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
        env={SYNTHETIC_MODE_ENV: "hang"},
    )
    assert result.observation is not None
    assert result.observation["outcome"] == "error"
    assert result.observation["reason_code"] == "timeout"
    blob = str(result.observation)
    assert SECRET_CANARY not in blob


def test_secret_canary_exception_is_not_in_observation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    context = default_probe_context("synth", deadline_seconds=20)
    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
        env={SYNTHETIC_MODE_ENV: "secret"},
    )
    assert result.observation is not None
    assert result.observation["outcome"] == "error"
    assert result.observation["reason_code"] == "probe_failed"
    assert SECRET_CANARY not in str(result.observation)
    assert SECRET_CANARY not in caplog.text
    diagnostic = result.observation.get("diagnostic") or ""
    assert "token=" not in diagnostic


def test_empty_worker_stdout_carries_bounded_stderr_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    caplog.set_level(logging.WARNING, logger="sase.llm_provider.usage.probe")
    context = default_probe_context("synth", deadline_seconds=20)

    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
        env={SYNTHETIC_MODE_ENV: "stderr_crash"},
    )

    assert result.observation is not None
    assert result.observation["outcome"] == "error"
    assert result.observation["reason_code"] == "probe_failed"
    diagnostic = result.observation.get("diagnostic") or ""
    assert "usage probe worker stderr" in diagnostic
    assert "worker crashed before stdout" in diagnostic
    assert SECRET_CANARY not in diagnostic
    assert "token=" not in diagnostic
    assert "\n" not in diagnostic
    assert len(diagnostic) <= 200
    assert "usage probe worker stderr for provider 'synth'" in caplog.text
    assert SECRET_CANARY not in caplog.text
    assert "token=" not in caplog.text


def test_descendant_processes_are_reaped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    pidfile = tmp_path / "child.pid"
    # This test proves descendant cleanup after timeout. Give a cold isolated
    # worker time to import the provider and write the PID file; the hanging-
    # plugin test covers the tighter production deadline path.
    context = default_probe_context("synth", deadline_seconds=5)
    result = run_usage_probe(
        context,
        isolate=True,
        plugin_spec=SYNTHETIC_PLUGIN_SPEC,
        env={
            SYNTHETIC_MODE_ENV: "descendants",
            SYNTHETIC_PIDFILE_ENV: str(pidfile),
        },
    )
    assert result.observation is not None
    assert result.observation["reason_code"] == "timeout"
    child_pid = int(pidfile.read_text(encoding="utf-8"))
    assert not _pid_alive(child_pid)


def test_in_process_type_error_calls_the_hook_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TypeError inside the hook is a failure, never a second mint."""
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    calls: list[object] = []

    class _MintOnce:
        def llm_usage_probe(self, context: object) -> None:
            calls.append(context)
            raise TypeError("credential mint failed internally")

    context = default_probe_context("muse", now=1_800_000_000.0)
    observation = probe_in_process(_MintOnce(), context, now=1_800_000_000.0)
    assert len(calls) == 1
    assert observation["outcome"] == "error"
    assert observation["reason_code"] == "probe_failed"


def test_in_process_positional_hook_is_called_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hook without a ``context`` parameter is called positionally, once."""
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    calls: list[object] = []

    class _LegacyHook:
        def llm_usage_probe(self, ctx: object) -> None:
            calls.append(ctx)
            return None

    context = default_probe_context("synth", now=1_800_000_000.0)
    observation = probe_in_process(_LegacyHook(), context, now=1_800_000_000.0)
    assert len(calls) == 1
    assert calls[0] is context
    assert observation["outcome"] == "unsupported"


def test_worker_environ_allows_proxy_and_config_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probes behind proxies and custom CA/config dirs keep their settings."""
    allowed = {
        "CLAUDE_CONFIG_DIR": "/tmp/sase-claude-cfg",
        "HTTP_PROXY": "http://proxy:8080",
        "HTTPS_PROXY": "http://proxy:8080",
        "NO_PROXY": "localhost",
        "ALL_PROXY": "http://proxy:8080",
        "NODE_EXTRA_CA_CERTS": "/tmp/sase-ca.pem",
        "http_proxy": "http://proxy:8080",
    }
    for name, value in allowed.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("MY_API_KEY", "secret")
    env = worker_environ()
    for name, value in allowed.items():
        assert env[name] == value
    assert "MY_API_KEY" not in env
