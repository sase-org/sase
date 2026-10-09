"""Live ``%auto`` plan-approval state readers.

The live ``agent_meta.json`` under ``SASE_ARTIFACTS_DIR`` is the only
source. Launch-time snapshots are never consulted, so toggling auto off
takes effect at the next gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, cast

from sase.plan_approval_choices import PLAN_APPROVAL_AUTO_MODE_CHOICES

__all__ = [
    "PlanAutoApprovalAction",
    "get_auto_plan_approval_action",
    "get_auto_plan_approval_argument",
    "is_auto_approve_active",
]

PlanAutoApprovalAction = Literal["approve", "epic", "tale"]


def _normalize_plan_action(value: object) -> PlanAutoApprovalAction | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in PLAN_APPROVAL_AUTO_MODE_CHOICES:
        return cast(PlanAutoApprovalAction, normalized)
    return None


def _read_agent_meta() -> dict[str, object]:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return {}
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_auto_plan_approval_action() -> PlanAutoApprovalAction | None:
    """Return the plan-specific auto-approval action, if one is active.

    The live ``agent_meta.json`` under ``SASE_ARTIFACTS_DIR`` is the only
    source. The ``SASE_AGENT_AUTO_*`` launch-time snapshot is never
    consulted, so an ``A`` toggle-off that strips the meta keys takes
    effect at the next gate. Missing, unreadable, or non-dict meta means
    no auto (fail closed).
    """
    raw_argument, has_raw_argument = _raw_auto_plan_argument()
    if has_raw_argument:
        if raw_argument == "epic":
            return "epic"
        if raw_argument == "tale":
            return "tale"
        # ``approve`` is an enabled-state compatibility sentinel. The plan
        # adapter receives and validates the opaque argument separately.
        return "approve"

    meta = _read_agent_meta()
    from sase.autonomy.record import read_record

    record = read_record(meta)
    if record is not None:
        # The record's selection reproduces the legacy derivation: bare
        # and ``:plan`` approve, ``:tale``/``:epic`` name their tier, and
        # manual (or an unusable record) asks.
        selection = record.get("selection")
        if selection in ("tale", "epic"):
            return selection  # type: ignore[return-value]
        if record.get("profile") != "manual":
            return "approve"
        return None

    action = _normalize_plan_action(meta.get("auto_approve_plan_action"))
    if action is not None:
        return action

    if meta.get("approve"):
        return "approve"

    return None


def get_auto_plan_approval_argument() -> str | None:
    """Return the optional raw argument retained from ``%auto``."""
    argument, present = _raw_auto_plan_argument()
    return argument if present else None


def _raw_auto_plan_argument() -> tuple[str | None, bool]:
    """Return the raw ``%auto`` argument from live meta only.

    The ``SASE_AGENT_AUTO_APPROVE_ARGUMENT`` / ``SASE_AGENT_AUTO_PLAN_ARGUMENT``
    launch-time snapshot is never consulted (see
    :func:`get_auto_plan_approval_action`). A stored autonomy record
    without legacy keys derives the argument from its selection, so
    record-only launches read identically.
    """
    meta = _read_agent_meta()
    if "auto_approve_argument" in meta:
        raw_value = meta.get("auto_approve_argument")
        if isinstance(raw_value, str):
            return raw_value.strip() or None, True
    from sase.autonomy.record import read_record

    record = read_record(meta)
    if record is not None:
        selection = record.get("selection")
        if selection in ("plan", "tale", "epic"):
            return selection, True
    return None, False


def is_auto_approve_active() -> bool:
    """Check if auto-approve is active from the live agent_meta.json.

    Returns True if the agent's ``agent_meta.json`` (located via
    SASE_ARTIFACTS_DIR) carries auto state. The ``SASE_AGENT_AUTO_APPROVE``
    launch-time snapshot is never consulted, so an ``A`` toggle-off takes
    effect at the next question gate. Missing, unreadable, or non-dict
    meta means no auto (fail closed).
    """
    _argument, has_argument = _raw_auto_plan_argument()
    if has_argument:
        return True
    meta = _read_agent_meta()
    from sase.autonomy.record import read_record

    record = read_record(meta)
    if record is not None:
        return record.get("profile") != "manual"
    return bool(meta.get("approve"))
