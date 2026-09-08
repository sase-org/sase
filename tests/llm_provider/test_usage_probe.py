"""Isolated probe worker, synthetic fourth provider, and secret-canary tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider.usage.probe import default_probe_context, run_usage_probe
from sase.llm_provider.usage.synthetic import (
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
    with override_flags(provider_usage_metrics=True):
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
    with override_flags(provider_usage_metrics=True):
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
    with override_flags(provider_usage_metrics=True):
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
    with override_flags(provider_usage_metrics=True):
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


def test_descendant_processes_are_reaped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    pidfile = tmp_path / "child.pid"
    context = default_probe_context("synth", deadline_seconds=1.5)
    with override_flags(provider_usage_metrics=True):
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
