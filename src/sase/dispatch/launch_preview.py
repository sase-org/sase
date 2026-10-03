"""Source-side `%dispatch` preview and portable-context construction."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.main.init_memory.config import project_memory_name
from sase.macro._directive_scan import DispatchDirectiveScan, scan_dispatch_directive

from .config import load_dispatch_config
from .models import MachineRecord, is_reference_id
from ._launch_common import (
    FLEET_SCHEMA_VERSION,
    RemoteDispatchLaunchError,
    RemoteDispatchLaunchPreview,
    optional_string,
)

_GIT_TIMEOUT_SECONDS = 2.0

#: Fleet contract version that carries ``agent_tab`` (contract 7). A target
#: older than this renders every dispatched agent on a derived machine tab.
_TAB_FLEET_CONTRACT_VERSION = 7


def preview_dispatch_launch(
    query: str,
    *,
    payload: Mapping[str, Any],
) -> RemoteDispatchLaunchPreview | None:
    """Validate a dispatch launch and return the request that would be sent."""
    scan = scan_dispatch_directive(query)
    if scan is None:
        return None
    _reject_local_only_payload(payload)
    config = load_dispatch_config()
    machine = _target_machine(config.machine_by_alias(), scan.target)
    tab_warning = _tab_dispatch_preflight(query, machine)
    context = _portable_project_context(payload, machine)
    intent = _launch_intent(scan, payload, context)
    operation_key = _operation_key(payload, scan, intent)
    from sase.core.agent_launch_facade import prompt_has_identity_directive

    if prompt_has_identity_directive(scan.prompt):
        # Prompt identity is the owner. Do not inject an operation-derived
        # name that the mobile bridge would prepend as a second %id.
        pass
    elif intent["follow"] and intent["name"] is None:
        intent["name"] = operation_key["operation_id"]
    fingerprint = _call_dict_binding(
        "fleet_launch_payload_fingerprint",
        intent,
        what="launch payload fingerprint",
    )
    request = {
        "schema_version": FLEET_SCHEMA_VERSION,
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
    provisional_locator = _provisional_follow_locator(
        machine,
        context["project_id"],
        _provisional_agent_id(intent, operation_key),
    )
    return RemoteDispatchLaunchPreview(
        target=scan.target,
        prompt=str(intent["prompt"]),
        source=scan.source,
        target_installation_id=machine.pinned_installation_id,
        target_status="ok",
        target_detail=tab_warning or "",
        portable_context=context,
        intent=intent,
        operation_key=operation_key,
        payload_fingerprint=fingerprint,
        request=request,
        provisional_locator=provisional_locator,
    )


def cached_fleet_contract_versions() -> dict[str, int]:
    """Return alias→fleet-contract versions from the cache-only hosts response.

    No-network source (same as the ``%tab`` + ``%dispatch`` preflight): a
    federation cache-only hosts response. Any failure reads as empty rather
    than blocking the caller. This may touch the federation cache on disk,
    so worker paths gate it behind their allow-disk flag; UI threads read
    the token-cached projection instead.
    """
    try:
        from sase.dispatch.federation import build_federation_facade

        facade = build_federation_facade()
        if not facade.config.enabled:
            return {}
        response = facade.catalog_hosts_sync(
            ({"schema_version": 1, "query": {"schema_version": 1, "limit": 1}},),
            cache_only=True,
            timeout_seconds=5.0,
        )
    except Exception:  # noqa: BLE001 - unknown versions read as empty.
        return {}
    if not isinstance(response, Mapping):
        return {}
    hosts = response.get("hosts")
    if not isinstance(hosts, Sequence) or isinstance(hosts, (str, bytes)):
        return {}
    versions: dict[str, int] = {}
    for host in hosts:
        if not isinstance(host, Mapping):
            continue
        alias = host.get("alias")
        if not isinstance(alias, str) or not alias:
            continue
        version = _coerce_contract_version(host.get("fleet_contract_schema_version"))
        if version is None:
            for nested_key in ("status", "hello", "host", "detail"):
                nested = host.get(nested_key)
                if isinstance(nested, Mapping):
                    version = _coerce_contract_version(
                        nested.get("fleet_contract_schema_version")
                    )
                    if version is not None:
                        break
        if version is not None:
            versions.setdefault(alias, version)
    return versions


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


def _tab_dispatch_preflight(query: str, machine: MachineRecord) -> str | None:
    """Check a ``%tab`` + ``%dispatch`` launch against the target's version.

    Returns a warning when the target's last-known contract version is
    unknown, None when it is current, and raises
    :class:`RemoteDispatchLaunchError` when it predates agent tabs. The
    version comes from a no-network source only (a federation cache-only
    host response); an unknown version warns and proceeds.
    """
    from sase.macro._tab_inheritance import (
        segment_has_active_tab_directive,
        split_prompt_segments,
    )

    segments, _ = split_prompt_segments(query)
    if not any(segment_has_active_tab_directive(segment) for segment in segments):
        return None
    required = _required_tab_contract_version()
    known = _read_cached_target_contract_version(machine.alias)
    if known is None:
        return (
            f"%tab travels with this dispatch, but {machine.alias!r} has no "
            "cached contract version; proceeding and the target keeps the "
            "tab when it runs fleet contract "
            f"v{required}+ (controllers first, or the fleet in lockstep)"
        )
    if known < required:
        raise RemoteDispatchLaunchError(
            f"dispatch target {machine.alias!r} runs fleet contract v{known}, "
            "which predates agent tabs "
            f"(v{required}); upgrade sase on the target first (controllers "
            "first, or the fleet in lockstep), or drop %tab"
        )
    return None


def _required_tab_contract_version() -> int:
    """Return the local fleet contract version, floored at the tab version."""
    try:
        version = require_rust_binding("fleet_contract_schema_version")()
    except Exception:  # noqa: BLE001 - preflight degrades to the floor.
        return _TAB_FLEET_CONTRACT_VERSION
    if isinstance(version, int) and version >= _TAB_FLEET_CONTRACT_VERSION:
        return version
    return _TAB_FLEET_CONTRACT_VERSION


def _read_cached_target_contract_version(alias: str) -> int | None:
    """Return the target's last-known fleet contract version, if cached.

    No-network source: a federation cache-only hosts response. Any failure
    (no federation config, worker unavailable, unknown shape) reads as
    unknown rather than blocking the launch.
    """
    try:
        from sase.dispatch.federation import build_federation_facade

        facade = build_federation_facade()
        if not facade.config.enabled:
            return None
        response = facade.catalog_hosts_sync(
            ({"schema_version": 1, "query": {"schema_version": 1, "limit": 1}},),
            cache_only=True,
            timeout_seconds=5.0,
        )
    except Exception:  # noqa: BLE001 - unknown version warns, never blocks.
        return None
    return _contract_version_for_alias(response, alias)


def _contract_version_for_alias(response: object, alias: str) -> int | None:
    """Extract one host's contract version from a cache-only hosts response."""
    if not isinstance(response, Mapping):
        return None
    hosts = response.get("hosts")
    if not isinstance(hosts, Sequence) or isinstance(hosts, (str, bytes)):
        return None
    for host in hosts:
        if not isinstance(host, Mapping):
            continue
        if host.get("alias") != alias:
            continue
        version = _coerce_contract_version(host.get("fleet_contract_schema_version"))
        if version is not None:
            return version
        for nested_key in ("status", "hello", "host", "detail"):
            nested = host.get(nested_key)
            if isinstance(nested, Mapping):
                version = _coerce_contract_version(
                    nested.get("fleet_contract_schema_version")
                )
                if version is not None:
                    return version
    return None


def _coerce_contract_version(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


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
    project_id = optional_string(payload.get("project")) or project_memory_name(
        Path.cwd()
    )
    patch_ref = _optional_reference(payload.get("patch_ref") or payload.get("patch"))
    revision = _optional_reference(payload.get("revision"))
    if revision is None and patch_ref is None:
        revision = _published_git_revision(Path.cwd())
    context = {
        "schema_version": FLEET_SCHEMA_VERSION,
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
        "schema_version": FLEET_SCHEMA_VERSION,
        "prompt": prompt,
        "request_id": _optional_reference(payload.get("request_id")),
        "display_name": optional_string(payload.get("display_name")),
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
        "schema_version": FLEET_SCHEMA_VERSION,
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
        "schema_version": FLEET_SCHEMA_VERSION,
        "project": {
            "schema_version": FLEET_SCHEMA_VERSION,
            "origin": {
                "schema_version": FLEET_SCHEMA_VERSION,
                "installation_id": machine.pinned_installation_id,
            },
            "project_id": str(project_id),
        },
        "agent_id": agent_id,
        # New spelling; core accepts ``agent_session_id`` as an alias of the
        # legacy locator key.
        "agent_session_id": None,
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
    text = optional_string(value)
    if text is None:
        return None
    if not is_reference_id(text):
        raise RemoteDispatchLaunchError(f"expected an opaque reference, got {text!r}")
    return text


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
    "cached_fleet_contract_versions",
    "preview_dispatch_launch",
]
