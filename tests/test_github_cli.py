"""Tests for the shared ``gh`` CLI runner."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

import pytest

from sase.core.retryability_wire import (
    RETRYABILITY_VERDICT_AFTER_DELAY,
    RETRYABILITY_VERDICT_PERMANENT,
    RETRYABILITY_VERDICT_TRANSIENT,
    RETRYABILITY_WIRE_SCHEMA_VERSION,
    RetryabilityVerdictWire,
)
from sase.github_cli import (
    DEFAULT_GH_TIMEOUT_SECONDS,
    GhCommandError,
    gh_api_json,
    run_gh,
)


def _verdict(
    *,
    retryable: bool,
    retry_after_seconds: int | None = None,
) -> RetryabilityVerdictWire:
    if retry_after_seconds is not None:
        kind = RETRYABILITY_VERDICT_AFTER_DELAY
    elif retryable:
        kind = RETRYABILITY_VERDICT_TRANSIENT
    else:
        kind = RETRYABILITY_VERDICT_PERMANENT
    return RetryabilityVerdictWire(
        schema_version=RETRYABILITY_WIRE_SCHEMA_VERSION,
        verdict=kind,
        reason="test",
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def test_run_gh_retries_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Sequence[str], dict[str, Any]]] = []
    sleeps: list[float] = []

    def fake_classifier(**_kwargs: Any) -> RetryabilityVerdictWire:
        return _verdict(retryable=True)

    def run_fn(
        args: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                list(args),
                1,
                stdout="",
                stderr="gh: HTTP 502 from github.com",
            )
        return subprocess.CompletedProcess(
            list(args),
            0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(
        "sase.github_cli.classify_failure_retryability",
        lambda *_args, **kwargs: fake_classifier(**kwargs),
    )

    result = run_gh(
        ["api", "repos/sase-org/sase"],
        run_fn=run_fn,
        sleep_fn=sleeps.append,
    )

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert result.attempts == 2
    assert sleeps == [1.0]
    assert len(calls) == 2
    assert calls[0][1]["timeout"] == DEFAULT_GH_TIMEOUT_SECONDS
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert calls[0][1]["env"]["GH_PROMPT_DISABLED"] == "1"


def test_run_gh_honors_classifier_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    calls = 0

    def run_fn(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                list(args),
                1,
                stdout="",
                stderr="API rate limit exceeded\nRetry-After: 7",
            )
        return subprocess.CompletedProcess(list(args), 0, stdout="{}", stderr="")

    monkeypatch.setattr(
        "sase.github_cli.classify_failure_retryability",
        lambda *_args, **_kwargs: _verdict(
            retryable=True,
            retry_after_seconds=7,
        ),
    )

    result = run_gh(["api", "rate_limit"], run_fn=run_fn, sleep_fn=sleeps.append)

    assert result.returncode == 0
    assert calls == 2
    assert sleeps == [7.0]


def test_run_gh_honors_x_ratelimit_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    calls = 0

    def run_fn(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                list(args),
                1,
                stdout="",
                stderr="x-ratelimit-reset: 107",
            )
        return subprocess.CompletedProcess(list(args), 0, stdout="{}", stderr="")

    monkeypatch.setattr(
        "sase.github_cli.classify_failure_retryability",
        lambda *_args, **_kwargs: _verdict(retryable=True),
    )

    result = run_gh(
        ["api", "rate_limit"],
        run_fn=run_fn,
        sleep_fn=sleeps.append,
        time_fn=lambda: 100.0,
    )

    assert result.returncode == 0
    assert calls == 2
    assert sleeps == [7.0]


def test_run_gh_does_not_retry_permanent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def run_fn(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            list(args),
            1,
            stdout="",
            stderr="gh: Not Found (HTTP 404)",
        )

    monkeypatch.setattr(
        "sase.github_cli.classify_failure_retryability",
        lambda *_args, **_kwargs: _verdict(retryable=False),
    )

    with pytest.raises(GhCommandError) as exc_info:
        run_gh(["api", "repos/missing"], check=True, run_fn=run_fn)

    assert calls == 1
    assert exc_info.value.result is not None
    assert exc_info.value.result.returncode == 1


def test_run_gh_retries_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    def run_fn(
        args: Sequence[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.TimeoutExpired(
                list(args),
                kwargs["timeout"],
                output="",
                stderr="stalled",
            )
        return subprocess.CompletedProcess(list(args), 0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "sase.github_cli.is_retryable_failure",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.github_cli.classify_failure_retryability",
        lambda *_args, **_kwargs: _verdict(retryable=True),
    )

    result = run_gh(
        ["api", "repos/sase-org/sase"], run_fn=run_fn, sleep_fn=sleeps.append
    )

    assert result.returncode == 0
    assert result.attempts == 2
    assert sleeps == [1.0]


def test_gh_api_json_parses_object() -> None:
    def run_fn(
        args: Sequence[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            list(args),
            0,
            stdout=json.dumps({"ok": True}),
            stderr="",
        )

    payload = gh_api_json("repos/sase-org/sase", run_fn=run_fn)

    assert payload == {"ok": True}
