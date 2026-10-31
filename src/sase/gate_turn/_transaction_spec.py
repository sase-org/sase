"""Request normalization and presentation helpers for gate-turn publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sase.notification_gates.model_request import GateSpec


def spec_from_request(request: Mapping[str, Any] | GateSpec) -> GateSpec:
    """Normalize *request* into a turn-row-managed spec with a request id."""
    if isinstance(request, GateSpec):
        if request.request_id:
            return replace(request, turn_row_managed=True)
        return replace(
            request,
            request_id=f"{request.kind}-{uuid4()}",
            turn_row_managed=True,
        )
    data = dict(request)
    if not data.get("request_id"):
        data["request_id"] = _default_request_id(data)
    return replace(GateSpec.from_mapping(data), turn_row_managed=True)


def stamp_pending_shell_on_spec(
    spec: GateSpec,
    *,
    member_artifacts_dir: str,
    member_timestamp: str,
) -> None:
    """Attach the pending turn member identity before the notification is published.

    Settlement-style ``raw_suffix`` names the new gate member so ACE can load an
    unloaded dir. Planner ``artifacts_dir`` / timestamps stay in place when the
    producer already recorded them.
    """
    action_data = dict(spec.presentation.get("action_data") or {})
    if member_timestamp:
        action_data.setdefault("raw_suffix", member_timestamp)
    if member_artifacts_dir and "artifacts_dir" not in action_data:
        kind = getattr(spec, "kind", None)
        stamp_member_dir = True
        if isinstance(kind, str) and kind:
            from sase.notification_gates.registry import adapter_for_kind

            # HITL (and any kind whose bundle path is ``artifacts_dir``)
            # reserves that action_data key for the durable bundle, so the
            # member identity rides on ``raw_suffix`` instead.
            stamp_member_dir = (
                adapter_for_kind(kind).legacy_directory_key != "artifacts_dir"
            )
        if stamp_member_dir:
            action_data["artifacts_dir"] = member_artifacts_dir
    # legacy agent-family spelling: pre-rename notifications carry
    # ``family_root_suffix``; new writers emit only
    # ``agent_session_root_suffix``.
    root = (
        action_data.get("agent_session_root_suffix")
        or action_data.get("family_root_suffix")
        or action_data.get("agent_root_timestamp")
        or action_data.get("agent_timestamp")
    )
    if isinstance(root, str) and root.strip():
        action_data.setdefault("agent_session_root_suffix", root.strip())
    action_data.pop("family_root_suffix", None)
    spec.presentation["action_data"] = action_data


def gate_label(spec: GateSpec, gate_id: str) -> str:
    """Return the human label recorded on the gate-turn member."""
    title = spec.presentation.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    notes = spec.presentation.get("notes")
    if isinstance(notes, list) and notes and isinstance(notes[0], str):
        return notes[0][:80]
    return f"{spec.kind}/{gate_id}"


def gate_reason(spec: GateSpec) -> str:
    """Return the wait reason recorded on the gate-turn member."""
    producer = spec.producer.get("agent") or spec.producer.get("chop")
    return f"wait for {producer}" if producer else "wait for gate decision"


def _default_request_id(data: Mapping[str, Any]) -> str:
    kind = data.get("kind")
    prefix = kind if isinstance(kind, str) and kind else "gate"
    return f"{prefix}-{uuid4()}"
