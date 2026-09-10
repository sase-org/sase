"""Shared probe strategy execution and drift classification helpers."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.llm_provider.usage.types import (
    UsageProbeContext,
    UsageReasonCode,
    bounded_probe_diagnostic,
)

ProbeStrategyAttempt = Callable[[UsageProbeContext], dict[str, Any]]

_JSON_RPC_DRIFT_CODES = frozenset({-32600, -32601, -32602})
_CLI_OPTION_REJECTION_PATTERNS = (
    re.compile(
        r"\b(?:unknown|unrecognized|invalid|unsupported)\s+"
        r"(?:option|flag|argument|parameter|params?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\berror:\s*(?:option|flag)\b.*\b(?:argument|value)\b.*\binvalid\b",
        re.IGNORECASE,
    ),
)
_ACP_METHOD_NOT_FOUND_MARKERS = (
    "method not found",
    "method_not_found",
    "unknown method",
)


@dataclass(frozen=True)
class ProbeStrategy:
    """One named usage-probe attempt in an ordered fallback chain."""

    slug: str
    attempt: ProbeStrategyAttempt


def run_probe_strategies(
    context: UsageProbeContext,
    strategies: Iterable[ProbeStrategy],
    *,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Run strategies until one succeeds or returns a non-drift failure."""
    ordered = tuple(strategies)
    if not ordered:
        raise ValueError("at least one probe strategy is required")
    drift_failures: list[tuple[str, Mapping[str, Any]]] = []
    last_observation: dict[str, Any] | None = None
    for index, strategy in enumerate(ordered):
        observation = strategy.attempt(context)
        last_observation = observation
        if _is_ok_observation(observation) and drift_failures:
            diagnostic = _recovery_diagnostic(drift_failures[0], strategy.slug)
            observation = _with_recovery_diagnostic(observation, diagnostic)
            if logger is not None:
                logger.warning(
                    "usage probe strategy recovered %s drift: %s",
                    context.provider,
                    diagnostic,
                )
            return observation
        if not _is_drift_failure(observation) or index == len(ordered) - 1:
            return observation
        drift_failures.append((strategy.slug, dict(observation)))
    assert last_observation is not None
    return last_observation


def classify_probe_failure(
    default_reason_code: UsageReasonCode = "probe_failed",
    *,
    json_rpc_error: Mapping[str, Any] | None = None,
    acp_error: Mapping[str, Any] | None = None,
    command_returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
) -> UsageReasonCode:
    """Map request-shape rejection evidence to ``vendor_drift``."""
    if (
        json_rpc_error is not None
        and _error_code(json_rpc_error) in _JSON_RPC_DRIFT_CODES
    ):
        return "vendor_drift"
    if acp_error is not None and _acp_method_not_found(acp_error):
        return "vendor_drift"
    if (
        command_returncode is not None
        and command_returncode != 0
        and _cli_option_rejection(f"{stdout}\n{stderr}")
    ):
        return "vendor_drift"
    return default_reason_code


def _is_ok_observation(observation: Mapping[str, Any]) -> bool:
    return observation.get("outcome") == "ok"


def _is_drift_failure(observation: Mapping[str, Any]) -> bool:
    return (
        observation.get("outcome") == "error"
        and observation.get("reason_code") == "vendor_drift"
    )


def _with_recovery_diagnostic(
    observation: Mapping[str, Any], recovery_diagnostic: str
) -> dict[str, Any]:
    payload = dict(observation)
    existing = payload.get("diagnostic")
    diagnostic = recovery_diagnostic
    if isinstance(existing, str) and existing.strip():
        diagnostic = f"{diagnostic}; {existing.strip()}"
    payload["diagnostic"] = bounded_probe_diagnostic(diagnostic)
    return payload


def _recovery_diagnostic(
    failure: tuple[str, Mapping[str, Any]], recovered_slug: str
) -> str:
    failed_slug, observation = failure
    detail = _failure_detail(observation)
    suffix = f" ({detail})" if detail else ""
    return bounded_probe_diagnostic(
        f"primary {failed_slug} failed{suffix}; recovered via {recovered_slug}"
    )


def _failure_detail(observation: Mapping[str, Any]) -> str:
    diagnostic = observation.get("diagnostic")
    if isinstance(diagnostic, str) and diagnostic.strip():
        return diagnostic.strip()
    reason_code = observation.get("reason_code")
    if isinstance(reason_code, str) and reason_code:
        return reason_code
    outcome = observation.get("outcome")
    return str(outcome or "")


def _error_code(error: Mapping[str, Any]) -> int | None:
    code = error.get("code")
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, float) and code.is_integer():
        return int(code)
    if isinstance(code, str):
        try:
            return int(code)
        except ValueError:
            return None
    return None


def _cli_option_rejection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _CLI_OPTION_REJECTION_PATTERNS)


def _acp_method_not_found(error: Mapping[str, Any]) -> bool:
    if _error_code(error) == -32601:
        return True
    evidence = _evidence_text(error)
    return any(marker in evidence for marker in _ACP_METHOD_NOT_FOUND_MARKERS)


def _evidence_text(value: Any) -> str:
    parts: list[str] = []
    _collect_evidence(value, parts)
    return " ".join(parts).lower()


def _collect_evidence(value: Any, parts: list[str]) -> None:
    if isinstance(value, str):
        parts.append(value)
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                parts.append(key)
            _collect_evidence(child, parts)
        return
    if isinstance(value, list | tuple):
        for child in value:
            _collect_evidence(child, parts)
