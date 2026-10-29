"""Project-scoped settings plus orchestration for the after-rebase gate."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sase.config.core import load_merged_config_for_local_path
from sase.core.rebase_gate import (
    ConfigWire,
    ContextWire,
    DecisionWire,
)
from sase.workflows.commit._rebase_gate_common import (
    RebaseGateOutcome,
    warn_without_evidence,
)
from sase.workflows.commit.hook_utils import (
    local_config_path_for_repo_root,
    normalize_path,
)
from sase.workflows.commit.rebase_gate_budget import (
    GateBudgetExhausted,
    GateWorkBudget,
)
from sase.workflows.commit.rebase_gate_execution import execute_gate

_DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class GateSettings:
    """Project-local command settings after Rust timeout preflight."""

    hook_command: str
    timeout_seconds: float


def run_after_rebase_gate(
    context: ContextWire,
    repo_root: str,
    *,
    budget: GateWorkBudget | None = None,
    settings: GateSettings | None = None,
) -> RebaseGateOutcome:
    """Execute the configured after-rebase hook for *context*.

    Loads ``commit_hooks`` for the explicit *repo_root* project layer (even
    when the host cwd belongs to another project), runs the command under
    the shared deadline, and returns the facade's verdict. Never raises for
    gate errors; cancellation is re-raised.
    """
    started = time.monotonic()
    budget = budget or GateWorkBudget()
    root = normalize_path(repo_root)
    if not isinstance(context, dict):
        return warn_without_evidence(
            started,
            "invalid pending rebase context; gate skipped",
            f"expected a context object, got {type(context).__name__}",
        )

    warning: tuple[str, str | None] | None = None
    if settings is None:
        settings, warning = load_after_rebase_gate_settings(root, budget)
    if warning is not None:
        reason, diagnostics = warning
        return warn_without_evidence(
            started,
            reason,
            diagnostics,
        )
    if settings is None:
        return warn_without_evidence(
            started,
            "could not validate project configuration; rebase gate skipped",
            None,
        )
    if not settings.hook_command:
        return _classify_disabled(context, started, settings.timeout_seconds)
    return execute_gate(
        context,
        root,
        settings.hook_command,
        settings.timeout_seconds,
        started,
        budget,
    )


def load_after_rebase_gate_settings(
    repo_root: str,
    budget: GateWorkBudget,
) -> tuple[GateSettings | None, tuple[str, str | None] | None]:
    """Load project settings and validate numeric policy through Rust.

    Returns a visible warning tuple for invalid settings. Empty hooks are
    represented as disabled settings and do not trigger gate-context work.
    """
    root = normalize_path(repo_root)
    try:
        with budget.measure():
            config = load_merged_config_for_local_path(
                local_config_path_for_repo_root(root)
            )
    except GateBudgetExhausted:
        return None, (
            "rebase gate budget expired while loading project configuration",
            None,
        )
    except Exception as exc:  # noqa: BLE001 - config failure fails open
        return None, (
            "could not load project configuration; rebase gate skipped",
            str(exc),
        )

    hooks = config.get("commit_hooks", {})
    if not isinstance(hooks, dict):
        return None, (
            "invalid commit_hooks configuration; rebase gate skipped",
            f"expected an object, got {type(hooks).__name__}",
        )
    hook_raw = hooks.get("after_rebase", "")
    if not isinstance(hook_raw, str):
        return None, (
            "invalid commit_hooks.after_rebase; rebase gate skipped",
            f"expected a string, got {hook_raw!r}",
        )
    hook = hook_raw.strip()
    timeout_raw = hooks.get("after_rebase_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    timeout = _normalize_timeout(timeout_raw)
    if timeout is None:
        return None, (
            "invalid commit_hooks.after_rebase_timeout_seconds; rebase gate skipped",
            f"expected a numeric timeout, got {timeout_raw!r}",
        )
    try:
        with budget.measure():
            from sase.core.rebase_gate import (
                validate_rebase_gate_timeout_seconds,
            )

            timeout = validate_rebase_gate_timeout_seconds(timeout)
    except GateBudgetExhausted:
        return None, (
            "rebase gate budget expired while validating configuration",
            None,
        )
    except ValueError as exc:
        return None, (
            "invalid commit_hooks.after_rebase_timeout_seconds; rebase gate skipped",
            str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - missing binding fails open
        return None, (
            "rebase gate configuration policy unavailable; gate skipped",
            str(exc),
        )
    budget.set_timeout(timeout)
    if not hook:
        return GateSettings("", timeout), None
    return GateSettings(hook, timeout), None


def _normalize_timeout(value: Any) -> float | None:
    """Convert a numeric configuration value; Rust owns all numeric bounds."""
    if value is None:
        return _DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except OverflowError:
            return None
    return None


def _classify_disabled(
    context: ContextWire,
    started: float,
    timeout: float,
) -> RebaseGateOutcome:
    """Return the facade's skip verdict without launching a process."""
    from sase.core.rebase_gate import classify_rebase_gate_result

    config: ConfigWire = {
        "hook_command": "",
        "timeout_seconds": timeout,
    }
    try:
        decision = classify_rebase_gate_result(context, config, {}, None)
    except Exception as exc:  # noqa: BLE001 - facade failure fails open
        return warn_without_evidence(
            started,
            "rebase gate policy unavailable; gate skipped",
            str(exc),
        )
    decision_typed: DecisionWire = decision
    return RebaseGateOutcome(
        decision=decision_typed,
        duration_seconds=time.monotonic() - started,
        metadata_path=None,
        stdout_tail="",
        stderr_tail="",
    )
