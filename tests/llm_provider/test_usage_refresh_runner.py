"""Usage-refresh runner: synthetic probes, batch bounds, and secret hygiene."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider.usage import refresh_runner
from sase.llm_provider.usage.refresh_runner import _run_admitted_refresh
from sase.llm_provider.usage.types import UsageProbeResult
from sase.testing.usage_synthetic import (
    SECRET_CANARY,
    SYNTHETIC_MODE_ENV,
    SYNTHETIC_PLUGIN_SPEC,
)


@pytest.fixture
def runner_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    return tmp_path


def test_runner_collects_synthetic_provider(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SYNTHETIC_MODE_ENV, raising=False)
    results = _run_admitted_refresh(
        {
            "batch_deadline_seconds": 8,
            "provider_deadline_seconds": 6,
            "max_concurrent": 3,
            "plugin_specs": {"synth": SYNTHETIC_PLUGIN_SPEC},
            "providers": [
                {
                    "provider": "synth",
                    "context_id": "default",
                    "account_generation": 1,
                    "lease_id": "lease-synth",
                }
            ],
        }
    )
    assert results[0]["provider"] == "synth"
    assert results[0]["outcome"] == "ok"
    stored = (runner_home / "llm_provider_usage.json").read_text(encoding="utf-8")
    assert SECRET_CANARY not in stored
    assert "synth" in stored


def test_runner_reports_providers_that_miss_the_batch_deadline(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SYNTHETIC_MODE_ENV, "hang")
    jobs = [
        {
            "provider": f"p{index}",
            "context_id": "default",
            "account_generation": 1,
            "lease_id": f"lease-{index}",
            "plugin_spec": SYNTHETIC_PLUGIN_SPEC,
        }
        for index in range(4)
    ]
    results = _run_admitted_refresh(
        {
            "batch_deadline_seconds": 1.2,
            "provider_deadline_seconds": 0.4,
            "max_concurrent": 3,
            "plugin_specs": {f"p{index}": SYNTHETIC_PLUGIN_SPEC for index in range(4)},
            "providers": jobs,
        }
    )
    assert len(results) == 4
    assert {item["outcome"] for item in results} == {"error"}
    assert any(
        item["reason_code"] in {"deadline_exceeded", "timeout"} for item in results
    )


def test_batch_deadline_keeps_finished_probe_records(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe finishing during executor shutdown is collected, not rewritten.

    The wait loop breaks at the work deadline, but leaving the executor block
    waits for the running probe, which records its real observation and
    attempt. Recording ``deadline_exceeded`` on top would turn a success into
    backoff.
    """
    observations: list[dict[str, Any]] = []
    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        refresh_runner,
        "record_provider_usage_observation",
        lambda observation, *, now=None: observations.append(dict(observation)),
    )
    monkeypatch.setattr(
        refresh_runner,
        "record_provider_usage_refresh_attempt",
        lambda *args, **kwargs: attempts.append((args, kwargs)),  # noqa: ANN002,ANN003
    )
    monkeypatch.setattr(
        refresh_runner,
        "release_provider_usage_refresh",
        lambda *args, **kwargs: None,  # noqa: ANN002,ANN003
    )

    def _slow_ok(
        context: object,
        *,
        isolate: bool = True,
        plugin_spec: object = None,
        now: float | None = None,
    ) -> UsageProbeResult:
        time.sleep(  # sase-test-wait: past the work deadline, inside executor shutdown
            1.5
        )
        return UsageProbeResult(
            observation={
                "provider": "slow",
                "outcome": "ok",
                "reason_code": None,
            }
        )

    monkeypatch.setattr(refresh_runner, "run_usage_probe", _slow_ok)
    results = _run_admitted_refresh(
        {
            # The work deadline is started + 1.0; the probe lands at +1.5.
            "batch_deadline_seconds": 3.0,
            "provider_deadline_seconds": 5.0,
            "max_concurrent": 1,
            "providers": [
                {
                    "provider": "slow",
                    "context_id": "default",
                    "account_generation": 1,
                    "lease_id": "lease-slow",
                }
            ],
        }
    )
    assert len(results) == 1
    assert results[0]["provider"] == "slow"
    assert results[0]["outcome"] == "ok"
    assert len(observations) == 1
    assert observations[0]["outcome"] == "ok"
    assert len(attempts) == 1


def test_finish_job_records_reason_retry_after_and_adaptive(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        refresh_runner,
        "record_provider_usage_refresh_attempt",
        lambda *args, **kwargs: attempts.append((args, kwargs)),  # noqa: ANN002,ANN003
    )
    monkeypatch.setattr(
        refresh_runner,
        "release_provider_usage_refresh",
        lambda *args, **kwargs: None,  # noqa: ANN002,ANN003
    )
    refresh_runner._finish_job(
        {
            "provider": "codex",
            "context_id": "default",
            "account_generation": 1,
            "lease_id": "lease-codex",
        },
        "error",
        300.0,
        1_800_000_000.0,
        reason_code="rate_limited",
        retry_after_seconds=120.0,
    )

    assert len(attempts) == 1
    kwargs = attempts[0][1]
    assert kwargs["reason_code"] == "rate_limited"
    assert kwargs["retry_after_seconds"] == 120.0
    assert kwargs["adaptive"] is True


def test_run_one_provider_passes_observation_reason_to_attempt(
    runner_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        refresh_runner,
        "record_provider_usage_observation",
        lambda observation, *, now=None: None,
    )
    monkeypatch.setattr(
        refresh_runner,
        "record_provider_usage_refresh_attempt",
        lambda *args, **kwargs: attempts.append((args, kwargs)),  # noqa: ANN002,ANN003
    )
    monkeypatch.setattr(
        refresh_runner,
        "release_provider_usage_refresh",
        lambda *args, **kwargs: None,  # noqa: ANN002,ANN003
    )

    def _rate_limited(
        context: object,
        *,
        isolate: bool = True,
        plugin_spec: object = None,
        now: float | None = None,
    ) -> UsageProbeResult:
        return UsageProbeResult(
            observation={
                "provider": "codex",
                "outcome": "error",
                "reason_code": "rate_limited",
                "retry_after_seconds": 60.0,
            }
        )

    monkeypatch.setattr(refresh_runner, "run_usage_probe", _rate_limited)
    result = refresh_runner._run_one_provider(
        {
            "provider": "codex",
            "context_id": "default",
            "account_generation": 1,
            "lease_id": "lease-codex",
        },
        None,
        5.0,
        300.0,
        1_800_000_000.0,
    )

    assert result["outcome"] == "error"
    assert result["reason_code"] == "rate_limited"
    assert len(attempts) == 1
    kwargs = attempts[0][1]
    assert kwargs["reason_code"] == "rate_limited"
    assert kwargs["retry_after_seconds"] == 60.0
    assert kwargs["adaptive"] is True
