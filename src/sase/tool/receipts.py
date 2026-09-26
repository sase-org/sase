"""Verdict-receipt settlement adapter over the Rust receipt contract.

Rust owns mint eligibility, supersession, and lookup. This module is a thin,
fail-open adapter: it calls the Rust settle API after the E3 verdict has
settled and never changes the child result. A failed settle records a
diagnostic on the run's triage facts (best effort) and returns ``None``;
receipt lookup stays fail closed at its own call sites.
"""

from __future__ import annotations

import os
import time
from typing import Any

from sase.core.tool_run import tool_run_receipt_settle, tool_run_triage_record
from sase.telemetry.metrics import TOOL_RUN_RECORDING_ERRORS
from sase.tool.argv import ResolvedToolArgv
from sase.tool.observe import inc_tool_metric


def receipt_policy_for_resolved(resolved: ResolvedToolArgv) -> dict[str, Any] | None:
    """Return the catalog ``receipt:`` policy for *resolved*, if any."""

    definition = resolved.definition
    if not isinstance(definition, dict):
        return None
    policy = definition.get("receipt")
    return dict(policy) if isinstance(policy, dict) else None


def is_bypassed() -> bool:
    """Return whether this invocation bypassed the wrapped tool form."""

    return bool((os.environ.get("SASE_TOOL_BYPASS") or "").strip())


def settle_receipt_for_run(
    run_id: str,
    resolved: ResolvedToolArgv,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> dict[str, Any] | None:
    """Mint or supersede a verdict receipt for a settled run.

    Runs after wrapper settlement and E3 triage settlement on both the
    foreground and the claimed hand-off worker paths (both share
    ``run_recorded_body``). Always spawns nothing and never raises: a
    missing binding, an unreadable store, or any other failure records a
    diagnostic and returns ``None`` while the child's exit code stands.
    """

    request: dict[str, Any] = {
        "run_id": run_id,
        "bypassed": is_bypassed(),
    }
    policy = receipt_policy_for_resolved(resolved)
    if policy is not None:
        request["policy"] = policy
    try:
        result = tool_run_receipt_settle(
            request,
            store_path=store_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    except Exception as exc:  # noqa: BLE001 - receipt minting is fail open.
        inc_tool_metric(TOOL_RUN_RECORDING_ERRORS, op="receipt")
        _record_receipt_diagnostic(run_id, f"receipt settle failed: {exc}")
        return None
    return result


def _record_receipt_diagnostic(run_id: str, diagnostic: str) -> None:
    """Persist one receipt diagnostic on the run's triage facts, best effort."""

    try:
        tool_run_triage_record(
            {
                "run_id": run_id,
                "stages": [],
                "run_facts": {
                    "continuation_mode": None,
                    "recipe_finished_ts": None,
                    "first_continued_exit_code": None,
                    "continuation_extra_ms": None,
                    "repeat_of_run_id": None,
                    "triaged_ts": None,
                    "diagnostics": [diagnostic],
                },
                "now_ts": int(time.time()),
            }
        )
    except Exception:  # noqa: BLE001 - diagnostics must fail open.
        pass


__all__ = [
    "is_bypassed",
    "receipt_policy_for_resolved",
    "settle_receipt_for_run",
]
