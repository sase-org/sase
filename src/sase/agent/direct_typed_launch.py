"""Direct user-initiated typed launches from ACE and ``sase run``.

A direct submission is already authorized. This module writes a durable
bundle the admission coordinator can reopen, then dispatches through
``dispatch_typed_launch_request`` without a LaunchApproval gate.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.launch_admission_store import UNITS_DIRNAME, admission_dir, read_json
from sase.agent.launch_request_planning import (
    expand_prompt_for_typed_launch,
    prepare_typed_launch_plan,
    resolve_typed_launch_selected_project,
    typed_launch_project_display_name,
)
from sase.agent.launch_request_types import (
    DIRECT_TYPED_LAUNCH_KIND,
    ApprovedLaunchDispatchResult,
    LaunchRequestError,
)
from sase.core.paths import sase_subdir
from sase.monitor.transaction import write_json_marker_atomic
from sase.notification_gates.paths import REQUEST_FILENAME

_TYPED_LAUNCHES_SUBDIR = "typed_launches"


def _write_direct_typed_launch_bundle(
    *,
    prompt: str,
    expanded_prompt: str,
    typed_plan: Mapping[str, Any],
    source_cwd: str,
    source_surface: str,
    selected_project: str | None,
    project_file: str | None = None,
    safe_inputs: Mapping[str, Any] | None = None,
    unit_dispatch_metadata: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Atomically persist a coordinator-readable direct typed-launch bundle."""
    digest = str(typed_plan.get("content_digest") or "")
    if not digest:
        raise LaunchRequestError(
            "invalid_request",
            "typed_plan",
            "typed launch plan is missing content_digest",
        )
    request_id = request_id or f"launch-{uuid4()}"
    payload: dict[str, Any] = {
        "request_id": request_id,
        "source_surface": source_surface,
        "typed_plan": dict(typed_plan),
        "plan_digest": digest,
        "plan_schema_version": typed_plan.get("schema_version"),
        "dispatch": {"cwd": source_cwd, "prompt": prompt},
        "submitted_prompt": prompt,
        "expanded_prompt": expanded_prompt,
        "safe_inputs": dict(safe_inputs or {}),
    }
    if unit_dispatch_metadata:
        payload["unit_dispatch_metadata"] = dict(unit_dispatch_metadata)
    if selected_project:
        payload["selected_project"] = selected_project
        display = typed_launch_project_display_name(selected_project)
        if display:
            payload["selected_project_display"] = display
    if project_file:
        payload["project_file"] = project_file
    envelope: dict[str, object] = {
        "kind": DIRECT_TYPED_LAUNCH_KIND,
        "request_id": request_id,
        "payload": payload,
    }
    bundle_dir = sase_subdir(_TYPED_LAUNCHES_SUBDIR) / request_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    write_json_marker_atomic(bundle_dir / REQUEST_FILENAME, envelope)
    return bundle_dir, payload


def write_typed_launch_bundle(
    *,
    prompt: str,
    expanded_prompt: str,
    typed_plan: Mapping[str, Any],
    source_cwd: str,
    source_surface: str,
    selected_project: str | None,
    project_file: str | None = None,
    safe_inputs: Mapping[str, Any] | None = None,
    unit_dispatch_metadata: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Persist a durable typed-launch bundle for an already planned request."""
    return _write_direct_typed_launch_bundle(
        prompt=prompt,
        expanded_prompt=expanded_prompt,
        typed_plan=typed_plan,
        source_cwd=source_cwd,
        source_surface=source_surface,
        selected_project=selected_project,
        project_file=project_file,
        safe_inputs=safe_inputs,
        unit_dispatch_metadata=unit_dispatch_metadata,
        request_id=request_id,
    )


def dispatch_direct_typed_launch(
    prompt: str,
    *,
    source_surface: str,
    source_cwd: str | None = None,
    safe_inputs: Mapping[str, Any] | None = None,
    spawn_coordinator: bool = True,
) -> tuple[ApprovedLaunchDispatchResult, Path] | None:
    """Plan, persist, and admit a user-initiated typed launch.

    Returns ``None`` when the expanded prompt has no active ``%if`` / ``%proc``.
    """
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.core.agent_launch_facade import sanitize_condition_inputs
    from sase.xprompt.code_value import (
        TYPED_LAUNCH_UNITS_DISABLED_MESSAGE,
        typed_launch_units_enabled,
    )
    from sase.xprompt.directives import DirectiveError, has_typed_launch_directive

    try:
        expanded_prompt = expand_prompt_for_typed_launch(prompt)
    except DirectiveError as exc:
        raise LaunchRequestError("invalid_request", "prompt", str(exc)) from exc
    if not has_typed_launch_directive(expanded_prompt):
        return None
    if not typed_launch_units_enabled():
        raise LaunchRequestError(
            "invalid_request",
            "prompt",
            TYPED_LAUNCH_UNITS_DISABLED_MESSAGE,
        )
    cwd = source_cwd or str(Path.cwd())
    selected_project = resolve_typed_launch_selected_project(expanded_prompt)
    typed_plan = prepare_typed_launch_plan(
        expanded_prompt, selected_project=selected_project
    )
    sanitized = sanitize_condition_inputs(dict(safe_inputs or {}))
    bundle_dir, payload = _write_direct_typed_launch_bundle(
        prompt=prompt,
        expanded_prompt=expanded_prompt,
        typed_plan=typed_plan,
        source_cwd=cwd,
        source_surface=source_surface,
        selected_project=selected_project,
        safe_inputs=sanitized,
    )
    cwd_path = Path(cwd).expanduser()
    original_cwd = Path.cwd()
    try:
        if cwd_path.is_dir() and cwd_path.resolve() != original_cwd:
            os.chdir(cwd_path)
        result = dispatch_typed_launch_request(
            bundle_dir,
            payload,
            spawn_coordinator=spawn_coordinator,
        )
    finally:
        if Path.cwd() != original_cwd:
            os.chdir(original_cwd)
    return result, bundle_dir


def typed_launch_run_message(result: ApprovedLaunchDispatchResult) -> str:
    """Return unit/admission language for a typed ``run.launch`` outcome."""
    summary = result.summary
    if summary is None:
        count = result.launched_count
        noun = "launch unit" if count == 1 else "launch units"
        return f"Launched {count} {noun}"
    total = int(summary.total)
    launched = int(summary.launched)
    noun = "launch unit" if total == 1 else "launch units"
    if not result.admission_complete:
        return f"Accepted {total} {noun}; admission continues in the background"
    parts = [f"Launched {launched} of {total} {noun}"]
    if summary.skipped:
        parts.append(f"{int(summary.skipped)} skipped")
    if summary.condition_errors:
        parts.append(f"{int(summary.condition_errors)} condition error(s)")
    if summary.launch_errors:
        parts.append(f"{int(summary.launch_errors)} launch error(s)")
    return "; ".join(parts)


def typed_launch_run_payload(
    result: ApprovedLaunchDispatchResult,
    bundle_dir: Path,
    *,
    unresolved_names: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build the durable ``run.launch`` success payload for typed dispatch."""
    from sase.core.agent_launch_wire import agent_launch_wire_to_json_dict
    from sase.xprompt.unresolved import format_unresolved_references_toast

    identities = _unit_identities(admission_dir(bundle_dir) / UNITS_DIRNAME)
    unit_results: list[dict[str, object]] = []
    for item in result.unit_results:
        entry: dict[str, object] = {
            "logical_id": item.logical_id,
            "outcome": item.outcome,
        }
        if item.message:
            entry["message"] = item.message
        identity = identities.get(item.logical_id)
        if identity:
            entry["identity"] = identity
        unit_results.append(entry)
    payload: dict[str, object] = {
        "count": len(result.results),
        "pids": [item.pid for item in result.results],
        "results": [_serialize_agent_result(item) for item in result.results],
        "request_agents_refresh": True,
        "schedule_agents_refresh": True,
        "admission_complete": bool(result.admission_complete),
    }
    if result.plan_digest:
        payload["plan_digest"] = result.plan_digest
    if result.summary is not None:
        payload["admission_summary"] = agent_launch_wire_to_json_dict(result.summary)
    if unit_results:
        payload["unit_results"] = unit_results
    if unresolved_names:
        payload["warning_messages"] = [
            format_unresolved_references_toast(tuple(unresolved_names))
        ]
    return payload


def _unit_identities(units_dir: Path) -> dict[str, str]:
    if not units_dir.is_dir():
        return {}
    identities: dict[str, str] = {}
    for path in units_dir.glob("*.json"):
        receipt = read_json(path)
        if not isinstance(receipt, dict):
            continue
        logical_id = receipt.get("logical_id")
        identity = receipt.get("identity")
        if isinstance(logical_id, str) and logical_id and isinstance(identity, str):
            identities[logical_id] = identity
    return identities


def _serialize_agent_result(result: object) -> dict[str, object]:
    return {
        "agent_name": getattr(result, "agent_name", None),
        "artifacts_dir": getattr(result, "artifacts_dir", ""),
        "cl_name": getattr(result, "cl_name", ""),
        "output_path": getattr(result, "output_path", ""),
        "pid": getattr(result, "pid", 0),
        "project_file": getattr(result, "project_file", ""),
        "project_name": getattr(result, "project_name", ""),
        "timestamp": getattr(result, "timestamp", ""),
        "workflow_name": getattr(result, "workflow_name", ""),
        "workspace_dir": getattr(result, "workspace_dir", ""),
        "workspace_num": getattr(result, "workspace_num", 0),
    }


__all__ = [
    "DIRECT_TYPED_LAUNCH_KIND",
    "dispatch_direct_typed_launch",
    "typed_launch_run_message",
    "typed_launch_run_payload",
    "write_typed_launch_bundle",
]
