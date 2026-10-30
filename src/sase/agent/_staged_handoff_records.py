"""Builders for staged-handoff records."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import uuid
from typing import Any

from sase.agent._staged_handoff_store import now_rfc3339
from sase.core.staged_handoff import STAGED_HANDOFF_WIRE_SCHEMA_VERSION


def _build_staged_record(
    *,
    kind: str,
    payload: Mapping[str, Any],
    successor_workspace: str,
    carry_allowed: bool,
    dirty_obligations_at_stage: list[str] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a staged-handoff record from host observations."""
    obligations = (
        list(dirty_obligations_at_stage)
        if dirty_obligations_at_stage is not None
        else _measure_dirty_obligations_at_stage()
    )
    return {
        "schema_version": STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
        "staged_id": staged_id or str(uuid.uuid4()),
        "kind": kind,
        "created_at": created_at or now_rfc3339(),
        "payload": dict(payload),
        "successor_workspace": successor_workspace,
        "carry_allowed": carry_allowed,
        "dirty_obligations_at_stage": obligations,
    }


def build_plan_staged_record(
    *,
    plan_file: str,
    original_file: str,
    dirty_obligations_at_stage: list[str] | None = None,
    extra_payload: Mapping[str, Any] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a plan staged-handoff record from host observations."""
    payload: dict[str, Any] = {
        "plan_file": plan_file,
        "original_file": original_file,
    }
    if extra_payload:
        payload.update(dict(extra_payload))
    return _build_staged_record(
        kind="plan",
        payload=payload,
        successor_workspace="none",
        carry_allowed=False,
        dirty_obligations_at_stage=dirty_obligations_at_stage,
        staged_id=staged_id,
        created_at=created_at,
    )


def build_questions_staged_record(
    *,
    questions: list[Any],
    dirty_obligations_at_stage: list[str] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a questions staged-handoff record (inherit, carry allowed)."""
    return _build_staged_record(
        kind="questions",
        payload={"questions": questions},
        successor_workspace="inherit",
        carry_allowed=True,
        dirty_obligations_at_stage=dirty_obligations_at_stage,
        staged_id=staged_id,
        created_at=created_at,
    )


def build_pipe_staged_record(
    *,
    payload: Mapping[str, Any],
    dirty_obligations_at_stage: list[str] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a pipe staged-handoff record (inherit, carry allowed)."""
    return _build_staged_record(
        kind="pipe",
        payload=payload,
        successor_workspace="inherit",
        carry_allowed=True,
        dirty_obligations_at_stage=dirty_obligations_at_stage,
        staged_id=staged_id,
        created_at=created_at,
    )


def build_monitor_staged_record(
    *,
    payload: Mapping[str, Any],
    dirty_obligations_at_stage: list[str] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
    carry_allowed: bool | None = None,
) -> dict[str, Any]:
    """Build a monitor staged-handoff record from a launch payload.

    Unprepared monitors inherit the workspace and allow carry. Prepared
    monitors keep commit-on-green: carry is refused so the starter does
    not synthesize it. Successor workspace is always inherit.
    """
    if carry_allowed is None:
        resources = payload.get("resources")
        nested_ref = (
            resources.get("prepared_intent_ref")
            if isinstance(resources, Mapping)
            else None
        )
        carry_allowed = not bool(payload.get("prepared_intent_ref") or nested_ref)
    return _build_staged_record(
        kind="monitor",
        payload=payload,
        successor_workspace="inherit",
        carry_allowed=carry_allowed,
        dirty_obligations_at_stage=dirty_obligations_at_stage,
        staged_id=staged_id,
        created_at=created_at,
    )


def build_gate_staged_record(
    *,
    payload: Mapping[str, Any],
    successor_workspace: str,
    carry_allowed: bool,
    dirty_obligations_at_stage: list[str] | None = None,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a gate staged-handoff record from a validated gate payload.

    The payload must already satisfy the Rust gate contract
    (``validate_gate_staged_payload``); this only wraps it in the outer
    record. The workspace disposition comes from the payload's
    ``workspace_mode`` via the gate staged-contract mapping.
    """
    obligations = (
        list(dirty_obligations_at_stage)
        if dirty_obligations_at_stage is not None
        else _measure_dirty_obligations_at_stage()
    )
    return {
        "schema_version": STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
        "staged_id": staged_id or str(uuid.uuid4()),
        "kind": "gate",
        "created_at": created_at or now_rfc3339(),
        "payload": dict(payload),
        "successor_workspace": successor_workspace,
        "carry_allowed": carry_allowed,
        "dirty_obligations_at_stage": obligations,
    }


def _measure_dirty_obligations_at_stage(
    artifacts_dir: str | None = None,
) -> list[str]:
    """Read-only snapshot of this turn's dirty-obligation ids.

    The list is evidence for the flag period, not permission to omit later
    obligations. A measurement failure yields an empty list.
    """
    raw = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        return []
    try:
        from sase.finalizers.declaration import load_latest_finalizer_context

        context = load_latest_finalizer_context(Path(raw))
    except Exception:
        return []
    return [
        item.obligation_id
        for item in context.obligations
        if getattr(item, "obligation_id", "")
    ]
