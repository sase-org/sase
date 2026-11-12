"""Host adapters and human-only CLI flow for local-command trust records.

The Rust config domain owns store validation and mutations. This module only
resolves project identity/config files, supplies host facts, and makes the
acknowledgment command require an interactive human terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, TextIO

import yaml  # type: ignore[import-untyped]

from sase.agent.identity import agent_marker_present, resolve_audit_identity
from sase.config.core import load_merged_config_for_local_path
from sase.config.local_trust import (
    LOCAL_COMMAND_TRUST_POLICY_VERSION,
    LOCAL_COMMAND_TRUST_WIRE_SCHEMA_VERSION,
    LocalCommandProjection,
    decide_local_command_trust,
    project_local_commands,
)
from sase.content_layout import (
    discover_project_root,
    resolve_project_config_read_path,
    resolve_project_config_write_path,
)
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_test_state_write_isolated


LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION = 1
LOCAL_COMMAND_TRUST_STORE_DIRECTORY = "local_config_trust"
LOCAL_COMMAND_TRUST_STORE_FILENAME = "records.json"


class _LocalCommandTrustManagementError(RuntimeError):
    """Raised when trust status or acknowledgment cannot be completed."""


@dataclass(frozen=True)
class _LocalCommandTrustContext:
    """One resolved checkout, logical config location, identity and projection."""

    checkout_root: Path
    selected_config_path: Path
    logical_config_path: str
    project_identity: str
    projection: LocalCommandProjection


def _local_command_trust_store_path() -> Path:
    """Return the fixed machine-local store path below SASE home."""
    return (
        sase_home()
        / LOCAL_COMMAND_TRUST_STORE_DIRECTORY
        / LOCAL_COMMAND_TRUST_STORE_FILENAME
    )


def _canonical(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise _LocalCommandTrustManagementError(
            f"cannot canonicalize checkout path {path}: {error}"
        ) from error


def _logical_config_location(root: Path, selected: Path) -> str:
    """Return the stable project-relative config choice included in the digest."""
    lexical = Path(os.path.abspath(selected))
    try:
        relative = lexical.relative_to(root)
    except ValueError as error:
        raise _LocalCommandTrustManagementError(
            f"selected config path {selected} is outside checkout {root}"
        ) from error
    return relative.as_posix()


def _requested_checkout(path: str | os.PathLike[str] | None) -> tuple[Path, Path]:
    requested = Path.cwd() if path is None else Path(path).expanduser()
    requested = _canonical(requested)
    root = discover_project_root(requested)
    if root is None:
        raise _LocalCommandTrustManagementError(
            f"{requested} is not inside a SASE project checkout"
        )
    root = _canonical(root)

    selected = resolve_project_config_read_path(root)
    if selected is None:
        selected = resolve_project_config_write_path(root)
    selected = Path(os.path.abspath(selected))

    is_config_argument = requested.name in {"sase.yml", "sase.yaml"}
    if not requested.exists() and not is_config_argument:
        raise _LocalCommandTrustManagementError(f"PATH does not exist: {requested}")
    if is_config_argument and _canonical(requested) != _canonical(selected):
        raise _LocalCommandTrustManagementError(
            f"{requested} is not the selected project config; expected {selected}"
        )
    if requested.is_file() and not is_config_argument:
        raise _LocalCommandTrustManagementError(
            "PATH must select a checkout or its selected sase.yml file"
        )
    return root, selected


def _read_local_layer(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise _LocalCommandTrustManagementError(
            f"cannot read project config {path}: {error}"
        ) from error
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise _LocalCommandTrustManagementError(
            f"cannot parse project config {path}: {error}"
        ) from error
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _LocalCommandTrustManagementError(
            f"project config {path} must contain a YAML mapping"
        )
    return value


def _project_identity(root: Path, config_path: Path) -> str:
    """Resolve a host project record only from its primary checkout or registry."""
    try:
        from sase.core.project_lifecycle_facade import list_project_records

        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:
        records = []

    root_key = str(root)
    projects = [
        record for record in records if record.is_project and not record.system_managed
    ]

    primary_matches: list[tuple[Any, Path]] = []
    for record in projects:
        if not record.workspace_dir:
            continue
        primary = _canonical(Path(record.workspace_dir))
        if str(primary) == root_key:
            primary_matches.append((record, primary))
    if len(primary_matches) == 1:
        record, primary = primary_matches[0]
        return _registered_identity(record.project_dir, primary)
    if primary_matches:
        return f"checkout:v1:{root}"

    registered: list[tuple[str, Path]] = []
    for record in projects:
        if not record.workspace_dir:
            continue
        primary = _canonical(Path(record.workspace_dir))
        if not primary.is_dir():
            continue
        try:
            # The workspace root may be selected in the project's own config.
            primary_config = resolve_project_config_read_path(primary)
            effective = load_merged_config_for_local_path(primary_config)
            from sase.workspace_provider.registry import (
                read_registry_file,
                registry_path,
            )
            from sase.workspace_provider.store import WorkspaceStore

            store = WorkspaceStore(str(primary), config=effective)
            registry = read_registry_file(registry_path(store.root_dir), strict=True)
            if registry is None:
                continue
            if _canonical(Path(registry.primary_workspace_dir)) != primary:
                continue
            if registry.project_key != store.project_key:
                continue
            if any(
                _canonical(Path(entry.checkout_dir)) == root
                for entry in registry.workspaces.values()
            ):
                registered.append(
                    (_registered_identity(record.project_dir, primary), primary)
                )
        except Exception:
            # Missing or ambiguous host membership never inherits project trust.
            continue

    identities = {identity for identity, _primary in registered}
    if len(identities) == 1:
        return next(iter(identities))
    return f"checkout:v1:{root}"


def _registered_identity(project_dir: str, primary: Path) -> str:
    project_record = _canonical(Path(project_dir))
    return f"project:v1:{project_record}:{primary}"


def _resolve_local_command_trust_context(
    path: str | os.PathLike[str] | None = None,
) -> _LocalCommandTrustContext:
    """Read one selected config snapshot and project its executable content."""
    root, config_path = _requested_checkout(path)
    local_layer = _read_local_layer(config_path)
    lower_config = load_merged_config_for_local_path(None)
    logical_location = _logical_config_location(root, config_path)
    projection = project_local_commands(
        local_layer,
        lower_macros=_mapping_or_empty(lower_config.get("macros")),
        lower_workflows=_mapping_or_empty(lower_config.get("workflows")),
        source="local_config",
        config_path=logical_location,
    )
    identity = _project_identity(root, config_path)
    return _LocalCommandTrustContext(
        checkout_root=root,
        selected_config_path=config_path,
        logical_config_path=logical_location,
        project_identity=identity,
        projection=projection,
    )


def _mapping_or_empty(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _store_snapshot(identity: str) -> dict[str, Any]:
    binding = require_rust_binding("local_command_trust_store_get")
    result = binding(str(sase_home()), identity)
    _validate_store_wire(result)
    return result


def _validate_store_wire(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _LocalCommandTrustManagementError(
            "Rust local-command trust store returned no mapping"
        )
    if payload.get("schema_version") != LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION:
        raise _LocalCommandTrustManagementError(
            "unsupported local-command trust store wire version: "
            f"{payload.get('schema_version')!r}"
        )
    return payload


def _store_allow(identity: str, digest: str) -> dict[str, Any]:
    audit_name = _require_human_terminal()
    store_path = _local_command_trust_store_path()
    assert_test_state_write_isolated(
        store_path, category="local-command trust acknowledgment"
    )
    binding = require_rust_binding("local_command_trust_store_allow")
    result = binding(
        str(sase_home()),
        identity,
        digest,
        LOCAL_COMMAND_TRUST_POLICY_VERSION,
        audit_name,
    )
    return _validate_store_wire(result)


def _store_revoke(identity: str) -> dict[str, Any]:
    _require_human_terminal()
    store_path = _local_command_trust_store_path()
    assert_test_state_write_isolated(
        store_path, category="local-command trust revocation"
    )
    binding = require_rust_binding("local_command_trust_store_revoke")
    result = binding(str(sase_home()), identity)
    return _validate_store_wire(result)


def _status_payload(context: _LocalCommandTrustContext) -> dict[str, Any]:
    snapshot = _store_snapshot(context.project_identity)
    record = snapshot.get("record")
    acknowledged_digest = record.get("digest") if isinstance(record, dict) else None
    acknowledged_policy = (
        record.get("policy_version") if isinstance(record, dict) else None
    )
    store_status = snapshot.get("status")
    store_reason = snapshot.get("reason")
    if store_status != "available":
        status = "untrusted"
        reason = str(store_reason or "trust store is unavailable or unsafe")
    else:
        decision = decide_local_command_trust(
            context.projection.digest,
            acknowledged_digest if isinstance(acknowledged_digest, str) else None,
            acknowledged_policy_version=(
                acknowledged_policy if isinstance(acknowledged_policy, int) else None
            ),
        )
        status = "trusted" if decision.trusted else "review_required"
        reason = decision.reason
    return {
        "schema_version": LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
        "status": status,
        "project_identity": context.project_identity,
        "checkout_root": str(context.checkout_root),
        "selected_config_path": str(context.selected_config_path),
        "logical_config_path": context.logical_config_path,
        "current_digest": context.projection.digest,
        "acknowledged_digest": acknowledged_digest,
        "policy_version": context.projection.policy_version,
        "acknowledged_policy_version": acknowledged_policy,
        "blocked_paths": list(context.projection.blocked_paths),
        "reason": reason,
    }


def _status_local_commands(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return the current local-command trust status without mutating state."""
    return _status_payload(_resolve_local_command_trust_context(path))


def _require_human_terminal() -> str:
    try:
        if agent_marker_present():
            raise _LocalCommandTrustManagementError(
                "local command trust can only be changed by a human in a foreground terminal"
            )
    except _LocalCommandTrustManagementError:
        raise
    except Exception as error:
        raise _LocalCommandTrustManagementError(
            f"cannot determine agent or monitor identity; refusing trust mutation: {error}"
        ) from error

    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise _LocalCommandTrustManagementError(
                "local command trust changes require an interactive terminal"
            )
        if hasattr(os, "tcgetpgrp"):
            foreground = os.tcgetpgrp(sys.stdin.fileno())
            if foreground != os.getpgrp():
                raise _LocalCommandTrustManagementError(
                    "local command trust changes require the foreground terminal"
                )
        identity = resolve_audit_identity()
    except _LocalCommandTrustManagementError:
        raise
    except Exception as error:
        raise _LocalCommandTrustManagementError(
            f"cannot establish a human terminal identity; refusing trust mutation: {error}"
        ) from error
    if identity.source != "interactive":
        raise _LocalCommandTrustManagementError(
            "local command trust changes require a human identity"
        )
    return identity.name


def require_local_trust_human_terminal() -> None:
    """Argparse-side actor guard; mutation adapters repeat it at write time."""
    _require_human_terminal()


def _confirm(prompt: str, *, answer: str) -> bool:
    print(prompt, end="", flush=True)
    response = sys.stdin.readline()
    return response.strip().casefold() == answer


def _print_allow_preview(context: _LocalCommandTrustContext) -> None:
    print(
        "Project identity: " + json.dumps(context.project_identity, ensure_ascii=True)
    )
    print("Checkout: " + json.dumps(str(context.checkout_root), ensure_ascii=True))
    print(
        "Selected config: "
        + json.dumps(str(context.selected_config_path), ensure_ascii=True)
    )
    print(
        "Logical config location: "
        + json.dumps(context.logical_config_path, ensure_ascii=True)
    )
    print(f"Policy version: {context.projection.policy_version}")
    print(f"Digest: {context.projection.digest}")
    print("Canonical command-bearing projection:")
    # Rust's canonical JSON escapes JSON controls, so project text is never
    # interpreted as terminal styling or cursor movement.
    print(context.projection.canonical_json)


def allow_local_commands(
    path: str | os.PathLike[str] | None = None,
) -> int:
    """Preview, confirm, re-read and acknowledge one exact config snapshot."""
    try:
        _require_human_terminal()
        reviewed = _resolve_local_command_trust_context(path)
        status = _status_payload(reviewed)
        if status["status"] == "untrusted":
            raise _LocalCommandTrustManagementError(str(status["reason"]))
        if status["status"] == "trusted":
            print("This project's current local commands are already acknowledged.")
            return 0
        _print_allow_preview(reviewed)
        if not _confirm(
            "Type allow to acknowledge this exact configuration: ", answer="allow"
        ):
            print("Trust acknowledgment declined.", file=sys.stderr)
            return 1

        current = _resolve_local_command_trust_context(path)
        if (
            current.project_identity != reviewed.project_identity
            or current.logical_config_path != reviewed.logical_config_path
            or _canonical(current.selected_config_path)
            != _canonical(reviewed.selected_config_path)
            or current.projection.digest != reviewed.projection.digest
        ):
            raise _LocalCommandTrustManagementError(
                "configuration changed; review again"
            )
        outcome = _store_allow(
            reviewed.project_identity,
            reviewed.projection.digest,
        )
        if not outcome.get("changed"):
            print("This project's current local commands are already acknowledged.")
        else:
            print("Acknowledged the reviewed local command configuration.")
        return 0
    except _LocalCommandTrustManagementError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"local command trust acknowledgment failed: {error}", file=sys.stderr)
        return 1


def revoke_local_commands(
    path: str | os.PathLike[str] | None = None,
) -> int:
    """Require an interactive human confirmation and revoke this project record."""
    try:
        _require_human_terminal()
        reviewed = _resolve_local_command_trust_context(path)
        status = _status_payload(reviewed)
        print(
            "Project identity: "
            + json.dumps(reviewed.project_identity, ensure_ascii=True)
        )
        print(
            "Selected config: "
            + json.dumps(str(reviewed.selected_config_path), ensure_ascii=True)
        )
        if status.get("acknowledged_digest"):
            print(f"Acknowledged digest: {status['acknowledged_digest']}")
        else:
            print("No current acknowledgment is stored.")
        if not _confirm(
            "Type revoke to remove this project's acknowledgment: ", answer="revoke"
        ):
            print("Trust revocation declined.", file=sys.stderr)
            return 1
        current = _resolve_local_command_trust_context(path)
        if current.project_identity != reviewed.project_identity or _canonical(
            current.selected_config_path
        ) != _canonical(reviewed.selected_config_path):
            raise _LocalCommandTrustManagementError(
                "project identity or selected config changed; review again"
            )
        _require_human_terminal()
        outcome = _store_revoke(reviewed.project_identity)
        message = (
            "Revoked this project's local command acknowledgment."
            if outcome.get("changed")
            else "This project had no local command acknowledgment to revoke."
        )
        print(message)
        return 0
    except _LocalCommandTrustManagementError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"local command trust revocation failed: {error}", file=sys.stderr)
        return 1


def print_trust_status(
    path: str | os.PathLike[str] | None = None,
    *,
    as_json: bool = False,
    stdout: TextIO | None = None,
) -> int:
    """Print structured status, distinguishing untrusted and operational errors."""
    stream = sys.stdout if stdout is None else stdout
    try:
        payload = _status_local_commands(path)
        code = 0 if payload["status"] == "trusted" else 1
    except Exception as error:
        payload = {
            "schema_version": LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
            "status": "operational_error",
            "reason": str(error),
        }
        code = 2

    if as_json:
        print(
            json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2),
            file=stream,
        )
        return code
    if payload.get("status") == "operational_error":
        print(
            f"Unable to read local command trust status: {payload['reason']}",
            file=stream,
        )
        return code
    print(f"Status: {payload['status']}", file=stream)
    print(
        "Project identity: "
        + json.dumps(payload["project_identity"], ensure_ascii=True),
        file=stream,
    )
    print(
        "Checkout: " + json.dumps(payload["checkout_root"], ensure_ascii=True),
        file=stream,
    )
    print(
        "Selected config: "
        + json.dumps(payload["selected_config_path"], ensure_ascii=True),
        file=stream,
    )
    print(
        "Logical config location: "
        + json.dumps(payload["logical_config_path"], ensure_ascii=True),
        file=stream,
    )
    print(f"Current digest: {payload['current_digest']}", file=stream)
    print(
        f"Acknowledged digest: {payload['acknowledged_digest'] or '(none)'}",
        file=stream,
    )
    print(f"Policy version: {payload['policy_version']}", file=stream)
    if payload["blocked_paths"]:
        print(
            "Command-bearing paths: " + ", ".join(payload["blocked_paths"]), file=stream
        )
    else:
        print("Command-bearing paths: (none)", file=stream)
    print(f"Reason: {payload['reason']}", file=stream)
    return code


__all__ = [
    "LOCAL_COMMAND_TRUST_STORE_DIRECTORY",
    "LOCAL_COMMAND_TRUST_STORE_FILENAME",
    "LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION",
    "allow_local_commands",
    "print_trust_status",
    "require_local_trust_human_terminal",
    "revoke_local_commands",
]
