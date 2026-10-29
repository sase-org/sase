"""Typed Python facade for Rust's shared rebase gate policy."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from sase.core.rust import require_rust_binding

REBASE_GATE_WIRE_SCHEMA_VERSION = 1

ChangeKind = Literal[
    "added",
    "modified",
    "deleted",
    "renamed",
    "copied",
    "type_changed",
    "unmerged",
]
Verdict = Literal["skip", "pass", "block", "warn"]


class ChangedPathWire(TypedDict):
    path: str
    kind: ChangeKind
    old_path: NotRequired[str]


class InputIdsWire(TypedDict):
    old_head: str
    upstream_tip: str
    merge_base: str


class RebaseFactsWire(TypedDict):
    schema_version: int
    repository_root: str
    old_head: str
    upstream_tip: str
    merge_base: str
    rebase_outcome: Literal["applied", "conflict", "no_op", "failed"]
    current_head: str
    current_tree: str
    local_changes: NotRequired[list[ChangedPathWire]]
    upstream_changes: NotRequired[list[ChangedPathWire]]


class ContextWire(TypedDict):
    schema_version: int
    repository_root: str
    inputs: list[InputIdsWire]
    current_head: str
    current_tree: str
    changed_paths: list[ChangedPathWire]


class ContextUpdateWire(TypedDict):
    schema_version: int
    repository_root: str
    current_head: str
    current_tree: str
    changed_paths: NotRequired[list[ChangedPathWire]]


class ConfigWire(TypedDict):
    hook_command: str
    timeout_seconds: float


class CommandFactsWire(TypedDict):
    exit_code: NotRequired[int | None]
    timed_out: NotRequired[bool]
    signal: NotRequired[int | None]
    spawn_error: NotRequired[str | None]


class FindingWire(TypedDict):
    path: str
    line: int
    module: str
    imported_name: str
    explanation: str


class ReportWire(TypedDict):
    schema_version: int
    checked_head: str
    checked_tree: str
    status: Literal["clean", "findings", "error"]
    findings: list[FindingWire]
    diagnostics: NotRequired[str | None]


class DecisionWire(TypedDict):
    schema_version: int
    verdict: Verdict
    reason: str
    findings: list[FindingWire]
    diagnostics: NotRequired[str | None]


def _check_binding_schema() -> None:
    version = int(require_rust_binding("rebase_gate_wire_schema_version")())
    if version != REBASE_GATE_WIRE_SCHEMA_VERSION:
        raise AttributeError(
            "sase_core_rs rebase gate wire is stale: "
            f"expected {REBASE_GATE_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _require_dict(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"sase_core_rs returned a non-dict {description}")
    if value.get("schema_version") != REBASE_GATE_WIRE_SCHEMA_VERSION:
        raise ValueError(f"sase_core_rs returned an incompatible {description}")
    return value


def build_rebase_gate_context(facts: RebaseFactsWire) -> ContextWire | None:
    """Return pending context for a divergent applied or conflicted rebase."""
    _check_binding_schema()
    result = require_rust_binding("build_rebase_gate_context")(dict(facts))
    if result is None:
        return None
    return _require_dict(result, "rebase gate context")  # type: ignore[return-value]


def merge_rebase_gate_contexts(
    existing: ContextWire | None, incoming: ContextWire | None
) -> ContextWire | None:
    """Merge a new rebase context into pending gate state."""
    _check_binding_schema()
    result = require_rust_binding("merge_rebase_gate_contexts")(
        {
            "schema_version": REBASE_GATE_WIRE_SCHEMA_VERSION,
            "existing": existing,
            "incoming": incoming,
        }
    )
    if result is None:
        return None
    return _require_dict(result, "merged rebase gate context")  # type: ignore[return-value]


def update_rebase_gate_context(
    context: ContextWire, update: ContextUpdateWire
) -> ContextWire:
    """Refresh pending context after repair while preserving original inputs."""
    _check_binding_schema()
    result = require_rust_binding("update_rebase_gate_context")(
        {
            "schema_version": REBASE_GATE_WIRE_SCHEMA_VERSION,
            "context": dict(context),
            "update": dict(update),
        }
    )
    return _require_dict(result, "updated rebase gate context")  # type: ignore[return-value]


def classify_rebase_gate_result(
    context: ContextWire,
    config: ConfigWire,
    command: CommandFactsWire,
    report: ReportWire | None,
) -> DecisionWire:
    """Classify checker facts; Rust validates whether a report may block."""
    _check_binding_schema()
    result = require_rust_binding("classify_rebase_gate_result")(
        {
            "schema_version": REBASE_GATE_WIRE_SCHEMA_VERSION,
            "context": dict(context),
            "config": dict(config),
            "command": dict(command),
            "report": dict(report) if report is not None else None,
        }
    )
    return _require_dict(result, "rebase gate decision")  # type: ignore[return-value]


__all__ = [
    "REBASE_GATE_WIRE_SCHEMA_VERSION",
    "ChangedPathWire",
    "InputIdsWire",
    "RebaseFactsWire",
    "ContextWire",
    "ContextUpdateWire",
    "ConfigWire",
    "CommandFactsWire",
    "FindingWire",
    "ReportWire",
    "DecisionWire",
    "build_rebase_gate_context",
    "merge_rebase_gate_contexts",
    "update_rebase_gate_context",
    "classify_rebase_gate_result",
]
