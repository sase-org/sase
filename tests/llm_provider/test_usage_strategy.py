"""Shared usage-probe strategy runner and drift classification tests."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from sase.llm_provider.usage._strategy import (
    ProbeStrategy,
    classify_probe_failure,
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
