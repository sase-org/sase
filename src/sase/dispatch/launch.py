"""Source-side `%dispatch` launch routing."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.main.init_memory.config import project_memory_name
from sase.xprompt._directive_scan import DispatchDirectiveScan, scan_dispatch_directive

from .config import load_dispatch_config, require_remote_dispatch_enabled
from .federation import (
    FederationWorkerResponseError,
    FederationWorkerUnavailable,
    build_federation_facade,
)
from .follow_store import (
    FollowStoreError,
    activate_dispatch_follow,
    prewrite_dispatch_follow,
    promote_family_follow,
)
from .launch_intent import (
    update_dispatch_launch_intent,
    upsert_dispatch_launch_intent,
)
from .models import DispatchError, MachineRecord, is_reference_id

_FLEET_SCHEMA_VERSION = 1
_GIT_TIMEOUT_SECONDS = 2.0


class RemoteDispatchLaunchError(RuntimeError):
    """Raised when a `%dispatch` launch cannot be safely submitted."""


@dataclass(frozen=True)
class _RemoteDispatchLaunchResult:
    """Successful source-side dispatch result for `run.launch` emission."""

    target: str
    prompt: str
    message: str
    payload: dict[str, object]


def maybe_dispatch_launch(
    query: str,
    *,
    payload: Mapping[str, Any],
    unresolved_names: Sequence[str] = (),
) -> _RemoteDispatchLaunchResult | None:
    """Submit a remote dispatch launch if *query* contains `%dispatch`."""
    scan = scan_dispatch_directive(query)
    if scan is None:
        return None
    try:
        require_remote_dispatch_enabled()
        _reject_local_only_payload(payload)
        config = load_dispatch_config()
        machine = _target_machine(config.machine_by_alias(), scan.target)
        context = _portable_project_context(payload, machine)
        intent = _launch_intent(scan, payload, context)
        operation_key = _operation_key(payload, scan, intent)
        if intent["follow"] and intent["name"] is None:
            intent["name"] = operation_key["operation_id"]
        fingerprint = _call_dict_binding(
            "fleet_launch_payload_fingerprint",
            intent,
            what="launch payload fingerprint",
        )
        request = {
            "schema_version": _FLEET_SCHEMA_VERSION,
            "key": operation_key,
            "target_installation_id": machine.pinned_installation_id,
            "intent": intent,
            "payload_fingerprint": fingerprint,
            "acceptance_window_seconds": max(config.request_timeout_seconds, 30.0),
        }
        _call_dict_binding(
            "fleet_validate_launch_request",
            request,
            what="launch request validation",
        )
        provisional_follow = _provisional_follow_locator(
            machine,
            context["project_id"],
            _provisional_agent_id(intent, operation_key),
        )
        upsert_dispatch_launch_intent(
            {
                "schema_version": _FLEET_SCHEMA_VERSION,
                "operation_key": operation_key,
                "target": scan.target,
                "target_installation_id": machine.pinned_installation_id,
                "prompt": scan.prompt,
                "portable_context": context,
                "payload_fingerprint": fingerprint,
                "follow": intent["follow"],
                "status": "unsent",
                "created_at_unix": time.time(),
                "updated_at_unix": time.time(),
            }
        )
        if intent["follow"]:
            prewrite_dispatch_follow(provisional_follow, operation_key)
        update_dispatch_launch_intent(operation_key, status="acceptance_uncertain")
        try:
            response = build_federation_facade().launch_sync(
                scan.target,
                request,
                timeout_seconds=config.request_timeout_seconds,
            )
        except FederationWorkerUnavailable as exc:
            update_dispatch_launch_intent(
                operation_key,
                status="unsent",
                error=str(exc),
            )
            raise
        except FederationWorkerResponseError as exc:
            update_dispatch_launch_intent(
                operation_key,
                status="acceptance_uncertain",
                error=str(exc),
            )
            raise
        receipt, decision, reason = _launch_receipt_from_response(response)
        if decision not in {"accept_new", "return_original_receipt"}:
            update_dispatch_launch_intent(
                operation_key,
                status=decision,
                receipt=receipt,
                error=reason,
            )
            raise RemoteDispatchLaunchError(
                f"remote dispatch {decision} for {scan.target}: {reason}"
            )
        source_status = "settled" if receipt.get("state") == "settled" else "accepted"
        update_dispatch_launch_intent(
            operation_key,
            status=source_status,
            receipt=receipt,
        )
        if intent["follow"]:
            _activate_receipt_follow(
                provisional_follow,
                receipt,
                operation_key=operation_key,
            )
        message = f"Dispatched launch to {scan.target} ({source_status})"
        return _RemoteDispatchLaunchResult(
            target=scan.target,
            prompt=str(intent["prompt"]),
            message=message,
            payload=_run_launch_payload(
                scan=scan,
                machine=machine,
                operation_key=operation_key,
                fingerprint=fingerprint,
                receipt=receipt,
                decision=decision,
                reason=reason,
                source_status=source_status,
                unresolved_names=unresolved_names,
            ),
        )
    except (DispatchError, FollowStoreError, ValueError) as exc:
        raise RemoteDispatchLaunchError(str(exc)) from exc
    except FederationWorkerUnavailable as exc:
        raise RemoteDispatchLaunchError(
            f"remote dispatch was not sent to {scan.target}: {exc}"
        ) from exc
    except FederationWorkerResponseError as exc:
        raise RemoteDispatchLaunchError(
            f"remote dispatch outcome is uncertain for {scan.target}: {exc}"
        ) from exc


def _target_machine(
    machines: Mapping[str, MachineRecord],
    target: str,
) -> MachineRecord:
    machine = machines.get(target)
    if machine is None:
        raise RemoteDispatchLaunchError(
            f"dispatch target {target!r} is not enrolled in dispatch.machines"
        )
    if machine.quarantined:
        reason = machine.quarantine_reason or "machine is quarantined"
        raise RemoteDispatchLaunchError(
            f"dispatch target {target!r} is quarantined: {reason}"
        )
    return machine


def _reject_local_only_payload(payload: Mapping[str, Any]) -> None:
    for key in ("launch_units", "inputs", "attachments", "files", "image_path"):
        value = payload.get(key)
        if value not in (None, "", (), [], {}):
            raise RemoteDispatchLaunchError(
                f"`%dispatch` cannot use local-only run payload field {key!r}"
            )


def _portable_project_context(
    payload: Mapping[str, Any],
    machine: MachineRecord,
) -> dict[str, Any]:
    project_id = _optional_string(payload.get("project")) or project_memory_name(
        Path.cwd()
    )
    patch_ref = _optional_reference(payload.get("patch_ref") or payload.get("patch"))
    revision = _optional_reference(payload.get("revision"))
    if revision is None and patch_ref is None:
        revision = _published_git_revision(Path.cwd())
    context = {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "provider_ref": _rust_reference(machine.provider_ref),
        "project_id": _rust_reference(project_id),
        "revision": None if revision is None else _rust_reference(revision),
        "patch_ref": None if patch_ref is None else _rust_reference(patch_ref),
    }
    _call_dict_binding(
        "fleet_validate_launch_intent",
        _launch_intent(
            DispatchDirectiveScan(target=machine.alias, prompt="validate", source=""),
            {},
            context,
        ),
        what="portable project context validation",
    )
    return context


def _published_git_revision(cwd: Path) -> str:
    root = _git_stdout(cwd, "rev-parse", "--show-toplevel")
    if root is None:
        raise RemoteDispatchLaunchError(
            "remote dispatch requires a Git revision or Patch evidence; this "
            "directory is not inside a Git checkout"
        )
    status = _git_stdout(Path(root), "status", "--porcelain")
    if status:
        raise RemoteDispatchLaunchError(
            "remote dispatch cannot use a dirty source checkout; commit and "
            "publish changes or provide Patch evidence before dispatch"
        )
    upstream = _git_stdout(
        Path(root),
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    if upstream is None:
        raise RemoteDispatchLaunchError(
            "remote dispatch cannot prove this revision is published because "
            "the current branch has no upstream"
        )
    ahead = _git_stdout(Path(root), "rev-list", "--count", f"{upstream}..HEAD")
    try:
        ahead_count = int(ahead or "0")
    except ValueError as exc:
        raise RemoteDispatchLaunchError(
            "remote dispatch could not determine whether HEAD is published"
        ) from exc
    if ahead is None or ahead_count > 0:
        raise RemoteDispatchLaunchError(
            "remote dispatch requires a published source revision; push local "
            "commits or provide Patch evidence before dispatch"
        )
    head = _git_stdout(Path(root), "rev-parse", "HEAD")
    if head is None:
        raise RemoteDispatchLaunchError("remote dispatch could not resolve Git HEAD")
    return head


def _launch_intent(
    scan: DispatchDirectiveScan,
    payload: Mapping[str, Any],
    context: Mapping[str, Any],
) -> dict[str, Any]:
    prompt = scan.prompt.strip()
    if not prompt:
        raise RemoteDispatchLaunchError("`%dispatch` launch prompt is empty")
    return {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "prompt": prompt,
        "request_id": _optional_reference(payload.get("request_id")),
        "display_name": _optional_string(payload.get("display_name")),
        "name": _optional_reference(payload.get("name")),
        "model": _optional_reference(payload.get("model")),
        "provider": _optional_reference(payload.get("provider")),
        "runtime": _optional_reference(payload.get("runtime")),
        "project": dict(context),
        "dry_run": payload.get("dry_run")
        if isinstance(payload.get("dry_run"), bool)
        else None,
        "follow": bool(payload.get("follow", True)),
        "references": [],
    }


def _operation_key(
    payload: Mapping[str, Any],
    scan: DispatchDirectiveScan,
    intent: Mapping[str, Any],
) -> dict[str, str | int]:
    source_identity = require_rust_binding("fleet_installation_identity_ensure")(
        str(sase_home())
    )
    record = source_identity.get("record") if isinstance(source_identity, dict) else {}
    controller_id = (
        record.get("installation_id") if isinstance(record, Mapping) else None
    )
    if not isinstance(controller_id, str) or not controller_id:
        raise RemoteDispatchLaunchError(
            "could not resolve source installation identity"
        )
    request_id = _optional_reference(payload.get("request_id"))
    operation_id = request_id or _deterministic_operation_id(scan.target, intent)
    return {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "controller_id": controller_id,
        "operation_id": operation_id,
    }


def _deterministic_operation_id(target: str, intent: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {"target": target, "intent": dict(intent)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"dispatch-{digest[:32]}"


def _provisional_follow_locator(
    machine: MachineRecord,
    project_id: object,
    agent_id: str,
) -> dict[str, object]:
    return {
        "schema_version": _FLEET_SCHEMA_VERSION,
        "project": {
            "schema_version": _FLEET_SCHEMA_VERSION,
            "origin": {
                "schema_version": _FLEET_SCHEMA_VERSION,
                "installation_id": machine.pinned_installation_id,
            },
            "project_id": str(project_id),
        },
        "agent_id": agent_id,
        "family_id": None,
    }


def _provisional_agent_id(
    intent: Mapping[str, Any],
    operation_key: Mapping[str, Any],
) -> str:
    name = _optional_reference(intent.get("name"))
    if name is not None:
        return name
    operation_id = operation_key.get("operation_id")
    return str(operation_id)


def _activate_receipt_follow(
    provisional_locator: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    operation_key: Mapping[str, Any],
) -> None:
    logical = receipt.get("logical_locator")
    if not isinstance(logical, Mapping):
        return
    if dict(logical) != dict(provisional_locator) and logical.get("family_id"):
        promote_family_follow(provisional_locator, logical)
    activate_dispatch_follow(logical, operation_key=operation_key)


def _launch_receipt_from_response(
    response: Mapping[str, Any],
) -> tuple[dict[str, Any], str, str]:
    hosts = response.get("hosts")
    if not isinstance(hosts, list) or len(hosts) != 1:
        raise RemoteDispatchLaunchError("federation launch returned no target host")
    host = hosts[0]
    if not isinstance(host, Mapping):
        raise RemoteDispatchLaunchError("federation launch host result is invalid")
    error = host.get("error")
    if isinstance(error, Mapping):
        raise RemoteDispatchLaunchError(
            str(error.get("message") or "federation launch host failed")
        )
    payload = host.get("payload")
    if not isinstance(payload, Mapping):
        raise RemoteDispatchLaunchError("federation launch returned no receipt payload")
    receipt = payload.get("receipt")
    if not isinstance(receipt, Mapping):
        raise RemoteDispatchLaunchError("federation launch response is missing receipt")
    decision = str(payload.get("decision") or "")
    reason = str(payload.get("reason") or "")
    return dict(receipt), decision, reason


def _run_launch_payload(
    *,
    scan: DispatchDirectiveScan,
    machine: MachineRecord,
    operation_key: Mapping[str, Any],
    fingerprint: Mapping[str, Any],
    receipt: Mapping[str, Any],
    decision: str,
    reason: str,
    source_status: str,
    unresolved_names: Sequence[str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "count": 0,
        "pids": [],
        "results": [],
        "request_agents_refresh": True,
        "schedule_agents_refresh": True,
        "dispatch": {
            "target": scan.target,
            "source": scan.source,
            "target_installation_id": machine.pinned_installation_id,
            "operation_key": dict(operation_key),
            "payload_fingerprint": dict(fingerprint),
            "decision": decision,
            "reason": reason,
            "state": receipt.get("state"),
            "source_status": source_status,
            "receipt": dict(receipt),
        },
    }
    if unresolved_names:
        from sase.xprompt.unresolved import format_unresolved_references_toast

        payload["warning_messages"] = [
            format_unresolved_references_toast(tuple(unresolved_names))
        ]
    return payload


def _call_dict_binding(
    name: str, payload: Mapping[str, Any], *, what: str
) -> dict[str, Any]:
    try:
        result = require_rust_binding(name)(dict(payload))
    except Exception as exc:
        raise RemoteDispatchLaunchError(f"{what} failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RemoteDispatchLaunchError(f"{what} returned a non-object result")
    return result


def _optional_reference(value: object) -> str | None:
    text = _optional_string(value)
    if text is None:
        return None
    if not is_reference_id(text):
        raise RemoteDispatchLaunchError(f"expected an opaque reference, got {text!r}")
    return text


def _optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _rust_reference(value: str) -> str:
    return value.replace("@", ":")


def _git_stdout(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


__all__ = [
    "RemoteDispatchLaunchError",
    "maybe_dispatch_launch",
]
