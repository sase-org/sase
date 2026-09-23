"""Shared usage-probe strategy runner and drift classification tests."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sase.llm_provider.usage._strategy import (
    ProbeStrategy,
    classify_probe_failure,
    detect_rate_limit,
    run_probe_strategies,
)
from sase.llm_provider.usage.probe import default_probe_context


def _observation(
    outcome: str, reason_code: str | None = None, diagnostic: str | None = None
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "reason_code": reason_code,
        "diagnostic": diagnostic,
    }


def test_strategy_runner_recovers_only_drift_and_shares_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("sase.tests.usage_strategy")
    caplog.set_level(logging.WARNING, logger=logger.name)
    context = default_probe_context("codex", now=1_800_000_000.0)
    seen_deadlines: list[float] = []

    def primary(attempt_context):
        seen_deadlines.append(attempt_context.deadline_at)
        return _observation(
            "error",
            "vendor_drift",
            "app-server account/rateLimits/read error -32602",
        )

    def fallback(attempt_context):
        seen_deadlines.append(attempt_context.deadline_at)
        return _observation("ok")

    result = run_probe_strategies(
        context,
        (
            ProbeStrategy("no_params", primary),
            ProbeStrategy("legacy_params", fallback),
        ),
        logger=logger,
    )

    assert result["outcome"] == "ok"
    assert seen_deadlines == [context.deadline_at, context.deadline_at]
    assert "primary no_params failed" in result["diagnostic"]
    assert "recovered via legacy_params" in result["diagnostic"]
    assert "usage probe strategy recovered codex drift" in caplog.text


def test_strategy_runner_stops_on_terminal_outcome() -> None:
    context = default_probe_context("claude", now=1_800_000_000.0)

    def unexpected_fallback(_attempt_context):
        raise AssertionError("terminal outcomes must not reach fallback")

    result = run_probe_strategies(
        context,
        (
            ProbeStrategy("primary", lambda _context: _observation("error", "timeout")),
            ProbeStrategy("fallback", unexpected_fallback),
        ),
    )

    assert result == _observation("error", "timeout")


@pytest.mark.parametrize("code", [-32600, -32601, -32602])
def test_json_rpc_request_shape_errors_are_vendor_drift(code: int) -> None:
    assert (
        classify_probe_failure(
            "probe_failed",
            json_rpc_error={"code": code, "message": "request shape rejected"},
        )
        == "vendor_drift"
    )


def test_non_shape_json_rpc_errors_keep_default_reason() -> None:
    assert (
        classify_probe_failure(
            "probe_failed",
            json_rpc_error={"code": -32042, "message": "server unavailable"},
        )
        == "probe_failed"
    )


def test_cli_option_rejections_require_nonzero_exit() -> None:
    stderr = "error: option '--max-budget-usd <amount>' argument '0' is invalid"
    assert (
        classify_probe_failure(
            "probe_failed",
            command_returncode=1,
            stderr=stderr,
        )
        == "vendor_drift"
    )
    assert (
        classify_probe_failure(
            "probe_failed",
            command_returncode=0,
            stderr=stderr,
        )
        == "probe_failed"
    )


def test_acp_method_not_found_is_vendor_drift() -> None:
    assert (
        classify_probe_failure(
            "probe_failed",
            acp_error={"code": -32000, "message": "unknown method _x.ai/billing"},
        )
        == "vendor_drift"
    )


def test_rate_limit_error_code_matches_without_text() -> None:
    evidence = detect_rate_limit(
        json_rpc_error={"code": 429, "message": "slow down"},
    )

    assert evidence is not None
    assert evidence.retry_after_seconds is None


def test_rate_limit_text_markers_match_in_stderr() -> None:
    assert (
        detect_rate_limit(stderr="Error: 429 Too Many Requests").retry_after_seconds
        is None
    )
    assert detect_rate_limit(stderr="usage backend is rate-limited") is not None
    assert detect_rate_limit(stdout="ERROR: rate limit exceeded") is not None


def test_rate_limit_header_retry_after_is_seconds() -> None:
    evidence = detect_rate_limit(
        command_returncode=1,
        stdout="ERROR: 429 Too Many Requests",
        stderr="retry-after: 120",
    )

    assert evidence is not None
    assert evidence.retry_after_seconds == pytest.approx(120.0)


def test_rate_limit_prose_retry_after_converts_minutes() -> None:
    evidence = detect_rate_limit(
        stdout="Rate limit exceeded for /usage, retry in 5 minutes",
    )

    assert evidence is not None
    assert evidence.retry_after_seconds == pytest.approx(300.0)


def test_rate_limit_field_retry_after_from_error_data() -> None:
    evidence = detect_rate_limit(
        acp_error={
            "code": 429,
            "message": "billing rate limit exceeded",
            "data": {"retryAfter": 90},
        },
    )

    assert evidence is not None
    assert evidence.retry_after_seconds == pytest.approx(90.0)


def test_rate_limit_retry_after_prose_inside_error_message() -> None:
    evidence = detect_rate_limit(
        json_rpc_error={
            "code": 429,
            "message": "rate limited; retry after 30 seconds",
        },
    )

    assert evidence is not None
    assert evidence.retry_after_seconds == pytest.approx(30.0)


def test_rate_limit_non_json_agy_output_with_stderr_hint() -> None:
    evidence = detect_rate_limit(
        stdout="ERROR: 429 Too Many Requests - quota exhausted",
        stderr="retry-after: 120",
    )

    assert evidence is not None
    assert evidence.retry_after_seconds == pytest.approx(120.0)


def test_rate_limit_ignores_unrelated_text() -> None:
    assert detect_rate_limit(stderr="server unavailable") is None
    assert detect_rate_limit(stderr="separate limitation applies") is None
    assert detect_rate_limit() is None
    assert detect_rate_limit(stdout="used 4290 tokens this week") is None


def test_rate_limit_ignores_429_inside_decimals() -> None:
    assert detect_rate_limit(stderr="score 0.429 exceeded threshold") is None
    assert detect_rate_limit(stdout="latency 429.5 ms average") is None
    assert detect_rate_limit(stderr="HTTP 429") is not None
    assert detect_rate_limit(stderr="429 Too Many Requests") is not None
    assert detect_rate_limit(stderr="status 429.") is not None


def test_rate_limit_ignores_quoted_method_path() -> None:
    assert (
        detect_rate_limit(
            json_rpc_error={
                "code": -32601,
                "message": "method not found: account/rateLimits/read",
            },
        )
        is None
    )


def test_rate_limit_ignores_unusable_retry_after() -> None:
    evidence = detect_rate_limit(
        stdout="rate limit exceeded",
        stderr="retry-after: soon",
    )

    assert evidence is not None
    assert evidence.retry_after_seconds is None
