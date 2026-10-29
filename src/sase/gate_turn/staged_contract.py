"""Durable gate staging contract: preparation building blocks.

This module prepares a normalized gate spec for staged publication without
activating CLI staging: it validates the spec through the existing gate
service seams, freezes the automatic-resolution outcome, captures
source-backed resource bytes into private staging storage, and projects the
persistable payload the publisher adopts after host completion.

The Rust core owns the payload schema, the request-ID linkage, the snapshot
metadata invariants, and the workspace-mode/disposition rule. Python remains
the adapter and filesystem observer: it assembles the spec, reads source
bytes, and writes snapshot files. Only the required creator identity and
policy fields are persisted, never the whole process environment.

Admission and reservation lifecycle belong to the caller (see
``sase.agent.staged_handoff``): preparation runs after the caller reserves
the one-handoff slot, snapshots are captured after admission, and any
preparation failure removes the snapshot directory it created. Crashes
between snapshot capture and record commit leave orphan snapshot
directories for the crash reconciler; they are never read without a staged
record that names them.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.staged_handoff import build_gate_staged_record
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    build_gate_staged_payload,
    validate_gate_staged_payload,
)
from sase.gate_turn.models import GateTurnError
from sase.notification_gates.durability import (
    materialize_resource,
    sha256_file,
)
from sase.notification_gates.model_request import GateSpec
from sase.notification_gates.models import GateError

#: Private staging storage for captured gate resource bytes, kept separate
#: from the public interaction-request bundle. One subdirectory per staged ID.
STAGED_GATE_RESOURCES_DIRNAME = ".sase_gate_staged_resources"


@dataclass(frozen=True)
class StagedGatePreparation:
    """Frozen preparation output for one staged gate."""

    request_id: str
    staged_id: str
    workspace_mode: str
    successor_workspace: str
    carry_allowed: bool
    auto_execute: bool
    spec: GateSpec
    decision: dict[str, Any]
    policy_block: dict[str, Any]
    payload: dict[str, Any] | None
    record: dict[str, Any] | None
    snapshot_dir: Path | None
    snapshots: tuple[dict[str, Any], ...]


def prepare_staged_gate(
    request: Mapping[str, Any] | GateSpec,
    *,
    creator: Mapping[str, Any],
    artifacts_dir: str,
    staged_id: str | None = None,
    created_at: str | None = None,
) -> StagedGatePreparation:
    """Validate *request* and capture its resources for staged publication.

    Returns the frozen effective spec, its auto evaluation, and — for gates
    that park for a human — the validated payload, the outer staged record,
    and the snapshot manifest. Synchronous auto gates return
    ``auto_execute=True`` with no payload, record, or snapshots: the caller
    proceeds inline exactly as today.
    """
    spec = _spec_from_request(request)
    adapter = _adapter_for_kind(spec.kind)
    _validate_gate_spec(spec, adapter)
    effective, decision, policy_block, auto_execute = _effective_auto_state(
        spec, adapter
    )
    if auto_execute:
        # Synchronous auto resolution stays inline exactly as today: it
        # writes no staged record and captures no snapshots.
        workspace_mode = (
            effective.turn.workspace if effective.turn is not None else "release"
        )
        successor_workspace, carry_allowed = _disposition(workspace_mode)
        return StagedGatePreparation(
            request_id=effective.request_id or "",
            staged_id=staged_id or str(uuid4()),
            workspace_mode=workspace_mode,
            successor_workspace=successor_workspace,
            carry_allowed=carry_allowed,
            auto_execute=True,
            spec=effective,
            decision=dict(decision),
            policy_block=dict(policy_block),
            payload=None,
            record=None,
            snapshot_dir=None,
            snapshots=(),
        )
    if effective.turn is None:
        raise GateTurnError(
            "staged gates require a turn block: turn-less gates publish "
            "inline and never hand off"
        )
    workspace_mode = _workspace_mode(effective)
    successor_workspace, carry_allowed = _disposition(workspace_mode)
    identity = str(staged_id or uuid4())
    root = Path(artifacts_dir) / STAGED_GATE_RESOURCES_DIRNAME
    snapshot_dir = root / identity
    try:
        snapshots = _capture_resource_snapshots(effective, snapshot_dir)
        payload = build_gate_staged_payload(
            {
                "request_id": effective.request_id,
                "spec": effective.to_dict(),
                "auto": {
                    "decision": dict(decision),
                    "policy_block": dict(policy_block),
                    "auto_execute": False,
                },
                "resources": list(snapshots),
                "creator": dict(creator),
                "workspace_mode": workspace_mode,
            }
        )
    except BaseException:
        _remove_snapshot_dir(snapshot_dir)
        raise
    try:
        record = build_gate_staged_record(
            payload=payload,
            successor_workspace=successor_workspace,
            carry_allowed=carry_allowed,
            staged_id=identity,
            created_at=created_at,
        )
    except BaseException:
        _remove_snapshot_dir(snapshot_dir)
        raise
    return StagedGatePreparation(
        request_id=effective.request_id or "",
        staged_id=identity,
        workspace_mode=workspace_mode,
        successor_workspace=successor_workspace,
        carry_allowed=carry_allowed,
        auto_execute=False,
        spec=effective,
        decision=dict(decision),
        policy_block=dict(policy_block),
        payload=payload,
        record=record,
        snapshot_dir=snapshot_dir,
        snapshots=tuple(snapshots),
    )


def rehydrate_staged_gate_spec(
    payload: Mapping[str, Any],
) -> GateSpec:
    """Rebuild the normalized spec from a validated staged gate payload.

    The persisted spec keeps its original ``source`` strings so
    ``edit_target: "origin"`` still opens the user's file; the publisher
    resolves bytes through the snapshot manifest instead. The rehydrated
    spec carries the host-internal ``turn_row_managed`` marker; raw user
    JSON can never assert it because ``from_mapping`` rejects it.
    """
    try:
        normalized = validate_gate_staged_payload(dict(payload))
    except StagedHandoffContractError as exc:
        raise GateTurnError(f"invalid staged gate payload: {exc}") from exc
    raw_spec = normalized.get("spec")
    if not isinstance(raw_spec, dict):
        raise GateTurnError("staged gate payload has no spec object")
    try:
        spec = GateSpec.from_mapping(raw_spec)
    except GateError as exc:
        raise GateTurnError(f"staged gate spec does not rehydrate: {exc}") from exc
    return dataclasses.replace(spec, turn_row_managed=True)


def read_staged_gate_snapshot_bytes(
    artifacts_dir: str,
    staged_id: str,
    resource_path: str,
) -> bytes:
    """Return the staged bytes captured for *resource_path*.

    Reads only inside this stage's snapshot directory; the path must stay
    under it. The publisher uses these bytes instead of reopening the
    mutable CLI working directory.
    """
    root = Path(artifacts_dir) / STAGED_GATE_RESOURCES_DIRNAME / staged_id
    target = (root / resource_path).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise GateTurnError(
            f"staged gate resource escapes its snapshot directory: {resource_path}"
        )
    try:
        return target.read_bytes()
    except OSError as exc:
        raise GateTurnError(
            f"staged gate resource is missing from storage: {resource_path}: {exc}"
        ) from exc


def discard_staged_gate_snapshot(artifacts_dir: str, staged_id: str) -> None:
    """Remove one stage's snapshot directory, if present."""
    _remove_snapshot_dir(
        Path(artifacts_dir) / STAGED_GATE_RESOURCES_DIRNAME / staged_id
    )


def collect_staged_gate_creator(
    *,
    artifacts_dir: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Collect the minimal creator identity the publisher needs.

    Only the fields publication requires are persisted: project and project
    file, source artifacts directory and timestamp, agent and session
    identity, and workspace/claim identity. The whole process environment
    is never stored.
    """
    root = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR") or ""
    if not root:
        raise GateTurnError("SASE_ARTIFACTS_DIR is unset")
    meta = _read_agent_meta(root)
    agent = os.environ.get("SASE_AGENT_NAME") or meta.get("name")
    if not isinstance(agent, str) or not agent.strip():
        raise GateTurnError(
            "no calling agent found; SASE_AGENT_NAME or agent_meta.json "
            "name is required"
        )
    project = project_name or _resolve_project_name(root)
    timestamp = os.path.basename(root.rstrip("/"))
    if not timestamp:
        raise GateTurnError(f"artifacts directory has no timestamp: {root}")
    return {
        "project": project,
        "project_file": _project_file_path(project),
        "artifacts_dir": root,
        "timestamp": timestamp,
        "agent": agent.strip(),
        "agent_session": _agent_session_value(meta),
        "target": meta.get("name") if isinstance(meta.get("name"), str) else agent,
        "workspace_num": _optional_int(meta.get("workspace_num")),
        "runner_pid": _optional_int(meta.get("pid")),
        "cl_name": meta.get("cl_name")
        if isinstance(meta.get("cl_name"), str)
        else None,
        "meta": {},
    }


def _spec_from_request(request: Mapping[str, Any] | GateSpec) -> GateSpec:
    if isinstance(request, GateSpec):
        spec = request
    else:
        data = dict(request)
        if not data.get("request_id"):
            data["request_id"] = _default_request_id(data)
        spec = GateSpec.from_mapping(data)
        return dataclasses.replace(
            spec,
            request_id=spec.request_id or _default_request_id(data),
            turn_row_managed=True,
        )
    if spec.request_id:
        return dataclasses.replace(spec, turn_row_managed=True)
    return dataclasses.replace(
        spec,
        request_id=_default_request_id({"kind": spec.kind}),
        turn_row_managed=True,
    )


def _default_request_id(data: Mapping[str, Any]) -> str:
    kind = data.get("kind")
    prefix = kind if isinstance(kind, str) and kind else "gate"
    return f"{prefix}-{uuid4()}"


def _adapter_for_kind(kind: str) -> Any:
    from sase.notification_gates.registry import adapter_for_kind

    return adapter_for_kind(kind)


def _validate_gate_spec(spec: GateSpec, adapter: Any) -> None:
    from sase.notification_gates.registry import validate_gate_spec

    validate_gate_spec(spec, adapter)


def _effective_auto_state(
    spec: GateSpec, adapter: Any
) -> tuple[GateSpec, dict[str, Any], dict[str, Any], bool]:
    from sase.notification_gates.service_evaluation import effective_auto_state

    return effective_auto_state(spec, adapter, request_id=spec.request_id)


def _workspace_mode(spec: GateSpec) -> str:
    if spec.turn is None:
        return "release"
    if spec.turn.workspace not in ("inherit", "release"):
        raise GateTurnError(
            f"staged gate workspace must be inherit or release: {spec.turn.workspace!r}"
        )
    return spec.turn.workspace


def _disposition(workspace_mode: str) -> tuple[str, bool]:
    if workspace_mode == "inherit":
        return "inherit", True
    return "none", False


def _capture_resource_snapshots(
    spec: GateSpec, snapshot_dir: Path
) -> list[dict[str, Any]]:
    """Materialize source-backed resources into staging storage.

    ``materialize_resource`` validates command executability at preparation
    time and preserves hash/executable semantics; the original ``source``
    string is preserved verbatim in the manifest so editable resources keep
    their ``edit_target: "origin"`` identity while publication reads the
    frozen snapshot bytes.
    """
    manifest: list[dict[str, Any]] = []
    for resource in spec.resources:
        if resource.source is None:
            continue
        try:
            target = materialize_resource(snapshot_dir, resource)
            digest = sha256_file(target)
            size_bytes = target.stat().st_size
        except GateError:
            raise
        except OSError as exc:
            raise GateTurnError(
                f"cannot snapshot staged gate resource {resource.path}: {exc}"
            ) from exc
        manifest.append(
            {
                "path": resource.path,
                "role": resource.role,
                "executable": resource.executable,
                "sha256": digest,
                "size_bytes": size_bytes,
                "origin": str(resource.source),
                "staged_relpath": f"{snapshot_dir.name}/{resource.path}",
            }
        )
    return manifest


def _remove_snapshot_dir(snapshot_dir: Path) -> None:
    import shutil

    shutil.rmtree(snapshot_dir, ignore_errors=True)


def _read_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    import json

    try:
        data = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _agent_session_value(meta: Mapping[str, Any]) -> str | None:
    try:
        from sase.plan_chain import agent_session_value
    except ImportError:
        return None
    value = agent_session_value(meta)
    return value if isinstance(value, str) and value.strip() else None


def _resolve_project_name(artifacts_dir: str) -> str:
    from sase.turns.settlement import project_name_from_artifacts_dir

    project_name = project_name_from_artifacts_dir(artifacts_dir)
    if project_name:
        return project_name
    try:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(os.getcwd())
    except Exception as exc:
        raise GateTurnError(
            "could not resolve project for staged gate preparation"
        ) from exc
    if project_name:
        return project_name
    raise GateTurnError("could not resolve project for staged gate preparation")


def _project_file_path(project_name: str) -> str:
    from sase.workflows.utils import get_project_file_path

    return get_project_file_path(project_name)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "STAGED_GATE_RESOURCES_DIRNAME",
    "StagedGatePreparation",
    "collect_staged_gate_creator",
    "discard_staged_gate_snapshot",
    "prepare_staged_gate",
    "read_staged_gate_snapshot_bytes",
    "rehydrate_staged_gate_spec",
]
