"""Ordered creation transaction for gate-shell backed gates."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.gate_shell import naming
from sase.gate_shell.member import create_gate_shell_member
from sase.gate_shell.models import (
    GateShellError,
    GateShellLaneError,
    GateShellRecord,
)
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.start_claim import (
    GateClaimMove,
    move_gate_shell_claim,
    restore_gate_shell_claim,
)
from sase.gate_shell.store import (
    find_gate_shell_by_gate_id,
    has_any_gate_shell,
    read_gate_shell_marker,
)
from sase.logs._bounded import log_file_lock
from sase.notification_gates.model_request import GateSpec
from sase.notification_gates.model_results import GateCreationResult
from sase.notification_gates.service import create_gate
from sase.plan_chain import agent_family_base
from sase.workflows.utils import get_project_file_path


@dataclass(frozen=True)
class GateShellCreation:
    """Result of creating a gate shell and its gate."""

    gate: GateCreationResult
    record: GateShellRecord
    project_file: str | None
    claim_move: GateClaimMove | None
    cl_name: str | None

    @property
    def should_handoff(self) -> bool:
        """Return whether the creator should hand off to the gate shell."""
        return not self.record.is_terminal

    def to_dict(self) -> dict[str, Any]:
        """Return the CLI descriptor with additive gate-shell metadata."""
        payload = self.gate.to_dict()
        payload["gate_shell"] = {
            "gate_id": self.record.gate_id,
            "member_agent_name": self.record.member_agent_name,
            "artifacts_dir": self.record.artifacts_dir,
            "state": self.record.gate_state,
            "workspace_policy": self.record.workspace_policy,
        }
        return payload


@dataclass(frozen=True)
class _CreatorContext:
    project_name: str
    project_file: str
    artifacts_dir: str
    timestamp: str
    target_name: str
    durable_lane: str
    meta: dict[str, Any]
    workspace_num: int | None
    runner_pid: int | None
    cl_name: str | None


def create_gate_shell(
    request: Mapping[str, Any] | GateSpec,
    *,
    before_auto_settle: Callable[[GateShellRecord, GateCreationResult], None]
    | None = None,
) -> GateShellCreation:
    """Create a gate-shell member, then create the durable gate."""
    spec = _spec_from_request(request)
    if spec.shell is None:
        raise GateShellError("gate shell creation requires a shell block")
    assert spec.request_id is not None

    project_name = _resolve_project_name()
    creator = _resolve_creator(project_name)
    lock_path = _gate_lane_lock_path(project_name, creator.durable_lane)
    with log_file_lock(lock_path):
        replay = find_gate_shell_by_gate_id(project_name, spec.request_id)
        if replay is not None:
            gate_result = create_gate(spec)
            record = _record_with_gate_result(project_name, replay, gate_result)
            return GateShellCreation(
                gate=gate_result,
                record=record,
                project_file=creator.project_file,
                claim_move=None,
                cl_name=creator.cl_name,
            )

        suffix = spec.shell.suffix or naming.allocate_gate_suffix(
            creator.durable_lane,
            has_existing_gate=has_any_gate_shell(project_name, creator.durable_lane),
        )
        label = _gate_label(spec, spec.request_id)
        artifacts_dir = create_gate_shell_member(
            project_name,
            creator.meta,
            lane=creator.durable_lane,
            suffix=suffix,
            prev_artifacts_timestamp=creator.timestamp,
            workspace_num=creator.workspace_num,
            gate_id=spec.request_id,
            gate_kind=spec.kind,
            label=label,
            reason=_gate_reason(spec),
            creator_agent=creator.meta.get("name")
            if isinstance(creator.meta.get("name"), str)
            else creator.target_name,
            timeout_seconds=spec.gate_timeout_seconds or 0.0,
            request_fingerprint=None,
            shell=spec.shell,
        )
        member_timestamp = os.path.basename(artifacts_dir.rstrip("/"))
        claim_move = move_gate_shell_claim(
            creator.project_file,
            creator.workspace_num,
            creator_pid=creator.runner_pid,
            artifacts_timestamp=member_timestamp,
            cl_name=creator.cl_name,
            workspace_policy=spec.shell.workspace,
        )
        _record_creator_claim(artifacts_dir, claim_move)
        if not claim_move.result.success:
            record = _read_required_record(project_name, artifacts_dir)
            settle_gate_shell(
                record,
                gate_state="failed",
                reason=claim_move.result.error or "workspace claim move failed",
                creator_live=True,
            )
            raise GateShellError(
                claim_move.result.error or "workspace claim move failed"
            )

        try:
            gate_result = create_gate(spec)
        except BaseException:
            record = _read_required_record(project_name, artifacts_dir)
            settle_gate_shell(
                record,
                gate_state="failed",
                reason="gate creation failed",
                creator_live=True,
            )
            restore_gate_shell_claim(
                creator.project_file,
                move=claim_move,
                cl_name=creator.cl_name,
            )
            raise

        record = _record_with_gate_result(
            project_name,
            _read_required_record(project_name, artifacts_dir),
            gate_result,
        )
        if gate_result.auto_resolution.get("state") == "resolved":
            if before_auto_settle is not None:
                before_auto_settle(record, gate_result)
                record = _read_required_record(project_name, artifacts_dir)
            record = settle_gate_shell(
                record,
                gate_state="answered",
                reason="auto-resolved",
                creator_live=True,
            )
            # The creator is still running in the workspace ``move_gate_shell_claim``
            # retitled to this gate shell above; restore its original claim now
            # that settlement (under ``creator_live=True``) left it untouched,
            # rather than leaking it as an unowned gate-shell claim.
            restore_gate_shell_claim(
                creator.project_file,
                move=claim_move,
                cl_name=creator.cl_name,
            )
        return GateShellCreation(
            gate=gate_result,
            record=record,
            project_file=creator.project_file,
            claim_move=claim_move,
            cl_name=creator.cl_name,
        )


def restore_creation_claim(creation: GateShellCreation) -> None:
    """Restore the creator claim captured by ``creation`` when present."""
    if creation.project_file is None or creation.claim_move is None:
        return
    restore_gate_shell_claim(
        creation.project_file,
        move=creation.claim_move,
        cl_name=creation.cl_name,
    )


def _spec_from_request(request: Mapping[str, Any] | GateSpec) -> GateSpec:
    if isinstance(request, GateSpec):
        if request.request_id:
            return request
        return replace(request, request_id=f"{request.kind}-{uuid4()}")
    data = dict(request)
    if not data.get("request_id"):
        data["request_id"] = _default_request_id(data)
    return GateSpec.from_mapping(data)


def _default_request_id(data: Mapping[str, Any]) -> str:
    kind = data.get("kind")
    prefix = kind if isinstance(kind, str) and kind else "gate"
    return f"{prefix}-{uuid4()}"


def _resolve_project_name() -> str:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        from sase.shells.settlement import project_name_from_artifacts_dir

        project_name = project_name_from_artifacts_dir(artifacts_dir)
        if project_name:
            return project_name
    try:
        from sase.workspace_provider import get_workspace_name

        project_name = get_workspace_name(os.getcwd())
        if project_name:
            return project_name
    except Exception as exc:
        raise GateShellLaneError(
            "could not resolve project for gate shell creation"
        ) from exc
    raise GateShellLaneError("could not resolve project for gate shell creation")


def _resolve_creator(project_name: str) -> _CreatorContext:
    from sase.agent._family_promotion import promote_agent_to_family
    import sase.monitor.store as monitor_store

    caller = monitor_store.default_caller() or os.environ.get("SASE_AGENT_NAME")
    artifacts_dir = monitor_store.caller_artifacts_dir()
    if not caller and artifacts_dir:
        caller = _read_meta(artifacts_dir).get("name")
    if not isinstance(caller, str) or not caller:
        raise GateShellLaneError(
            "no calling agent found; SASE_AGENT_NAME or SASE_ARTIFACTS_DIR is required"
        )
    try:
        ctx = monitor_store.resolve_caller_agent(
            project_name,
            caller,
            artifacts_dir=artifacts_dir,
        )
    except Exception as exc:
        raise GateShellLaneError(str(exc)) from exc

    raw_meta = _read_meta(ctx.record.artifact_dir)
    durable_lane = str(raw_meta.get("agent_family") or "").strip()
    target_name = str(raw_meta.get("name") or caller)
    if not durable_lane:
        promoted_name = promote_agent_to_family(ctx.record.artifact_dir, target_name)
        durable_lane = agent_family_base(promoted_name) or target_name
        raw_meta = _read_meta(ctx.record.artifact_dir)
    workspace_num = _optional_int(raw_meta.get("workspace_num"))
    runner_pid = _optional_int(raw_meta.get("pid"))
    cl_name = raw_meta.get("cl_name")
    return _CreatorContext(
        project_name=project_name,
        project_file=ctx.record.project_file or get_project_file_path(project_name),
        artifacts_dir=ctx.record.artifact_dir,
        timestamp=ctx.record.timestamp,
        target_name=target_name,
        durable_lane=durable_lane,
        meta=raw_meta,
        workspace_num=workspace_num,
        runner_pid=runner_pid,
        cl_name=cl_name if isinstance(cl_name, str) else None,
    )


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    path = Path(artifacts_dir) / "agent_meta.json"
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise GateShellLaneError(f"agent_meta.json at {artifacts_dir!r} is invalid")
    return data


def _gate_label(spec: GateSpec, gate_id: str) -> str:
    title = spec.presentation.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    notes = spec.presentation.get("notes")
    if isinstance(notes, list) and notes and isinstance(notes[0], str):
        return notes[0][:80]
    return f"{spec.kind}/{gate_id}"


def _gate_reason(spec: GateSpec) -> str:
    producer = spec.producer.get("agent") or spec.producer.get("chop")
    return f"wait for {producer}" if producer else "wait for gate decision"


def _record_with_gate_result(
    project_name: str,
    record: GateShellRecord,
    result: GateCreationResult,
) -> GateShellRecord:
    update_meta_fields(
        record.artifacts_dir,
        {
            "gate_bundle_path": str(result.bundle_path),
            "gate_notification_id": result.notification_id,
            "gate_request_fingerprint": result.hashes.get("request"),
        },
    )
    return read_gate_shell_marker(project_name, record.artifacts_dir) or record


def _record_creator_claim(artifacts_dir: str, move: GateClaimMove) -> None:
    claim = move.creator_claim
    if claim is None:
        return
    update_meta_fields(
        artifacts_dir,
        {
            "gate_creator_claim_pid": claim.pid,
            "gate_creator_claim_workflow": claim.workflow,
            "gate_creator_claim_artifacts_timestamp": claim.artifacts_timestamp,
            "gate_creator_claim_pinned": claim.pinned,
        },
    )


def _read_required_record(project_name: str, artifacts_dir: str) -> GateShellRecord:
    record = read_gate_shell_marker(project_name, artifacts_dir)
    if record is None:
        raise GateShellError(f"gate shell member missing at {artifacts_dir}")
    return record


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _gate_lane_lock_path(project_name: str, lane: str) -> Path:
    key = sha256(f"{project_name}\0{lane}".encode()).hexdigest()[:32]
    from sase.core.paths import sase_projects_dir

    return (
        sase_projects_dir()
        / project_name
        / "artifacts"
        / "ace-run"
        / f".gate-shell-{key}"
    )


__all__ = [
    "GateShellCreation",
    "create_gate_shell",
    "restore_creation_claim",
]
