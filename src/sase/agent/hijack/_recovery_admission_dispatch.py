"""Materialize recovery admission requests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack._recovery_admission_common import (
    RECOVERY_ADMISSION_METADATA_KEY,
    RECOVERY_ADMISSION_SOURCE_SURFACE,
    TYPED_LAUNCHES_SUBDIR,
    canonical_json,
    required_string,
    validate_descriptor_fields,
    validate_request_id,
    string_or_none,
)
from sase.agent.hijack._recovery_admission_dispatcher import (
    make_hijack_recovery_agent_dispatcher,
)
from sase.agent.launch_admission_store import read_json
from sase.core.atomic_json import write_json_marker_atomic

__all__ = [
    "dispatch_recovery_admission",
]


def dispatch_recovery_admission(
    descriptor: Mapping[str, Any],
    *,
    spawn_successor: Callable[..., Any] | None = None,
    resolve_session_plan: Callable[[str, str | None], Any] | None = None,
    spawn_coordinator: bool = True,
) -> tuple[Any, Path]:
    """Materialize and submit the exact typed recovery request idempotently."""
    from sase.agent.direct_typed_launch import typed_launch_project_display_name
    from sase.agent.launch_admission import dispatch_typed_launch_request
    from sase.core.paths import sase_subdir
    from sase.notification_gates.durability import file_lock
    from sase.notification_gates.paths import REQUEST_FILENAME

    payload = _typed_request_payload(descriptor, typed_launch_project_display_name)
    request_id = required_string(payload, "request_id")
    validate_request_id(request_id)
    bundle_dir = sase_subdir(TYPED_LAUNCHES_SUBDIR) / request_id
    request_path = bundle_dir / REQUEST_FILENAME
    envelope = {
        "kind": "direct_typed_launch",
        "request_id": request_id,
        "payload": payload,
    }
    bundle_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(bundle_dir / "recovery-request.lock", timeout=10.0):
        existing = read_json(request_path)
        if request_path.exists() and existing is None:
            raise ValueError(
                f"typed admission request {request_id} is unreadable or malformed"
            )
        if existing is not None:
            if canonical_json(existing) != canonical_json(envelope):
                raise ValueError(
                    f"typed admission request {request_id} has conflicting contents"
                )
        else:
            write_json_marker_atomic(request_path, envelope)
    dispatcher = make_hijack_recovery_agent_dispatcher(
        payload,
        bundle_dir=bundle_dir,
        spawn_successor=spawn_successor,
        resolve_session_plan=resolve_session_plan,
    )
    result = dispatch_typed_launch_request(
        bundle_dir,
        payload,
        agent_dispatcher=dispatcher,
        spawn_coordinator=spawn_coordinator,
    )
    return result, bundle_dir


def _typed_request_payload(
    descriptor: Mapping[str, Any],
    project_display: Callable[[str | None], str | None],
) -> dict[str, Any]:
    validate_descriptor_fields(descriptor)
    plan = descriptor.get("typed_plan")
    if not isinstance(plan, Mapping):
        raise ValueError("recovery descriptor has no typed plan")
    plan_dict = dict(plan)
    plan_digest = str(plan_dict.get("content_digest") or "")
    if plan_digest != str(descriptor.get("plan_digest") or ""):
        raise ValueError("recovery descriptor plan digest does not match")
    selected_project = required_string(descriptor, "project_name")
    payload: dict[str, Any] = {
        "request_id": required_string(descriptor, "admission_request_id"),
        "source_surface": RECOVERY_ADMISSION_SOURCE_SURFACE,
        "typed_plan": plan_dict,
        "plan_digest": plan_digest,
        "plan_schema_version": plan_dict.get("schema_version"),
        "dispatch": {
            "cwd": required_string(descriptor, "workspace_dir"),
            "prompt": required_string(descriptor, "prompt"),
        },
        "submitted_prompt": required_string(descriptor, "prompt"),
        "expanded_prompt": required_string(descriptor, "prompt"),
        "safe_inputs": {},
        "launch_submitted_at": required_string(descriptor, "launch_submitted_at"),
        "unit_dispatch_metadata": {
            RECOVERY_ADMISSION_METADATA_KEY: dict(descriptor),
        },
        "selected_project": selected_project,
    }
    display = project_display(selected_project)
    if display:
        payload["selected_project_display"] = display
    project_file = string_or_none(descriptor.get("project_file"))
    if project_file:
        payload["project_file"] = project_file
    return payload
