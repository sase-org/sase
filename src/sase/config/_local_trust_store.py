"""Rust-backed local-command trust store and status adapters."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from sase.agent.identity import agent_marker_present, resolve_audit_identity
from sase.config.local_trust import (
    LOCAL_COMMAND_TRUST_POLICY_VERSION,
    decide_local_command_trust,
)
from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.core.state_write_guard import assert_test_state_write_isolated

from ._local_trust_checkout import resolve_local_command_trust_context
from ._local_trust_support import (
    LOCAL_COMMAND_TRUST_STORE_DIRECTORY,
    LOCAL_COMMAND_TRUST_STORE_FILENAME,
    LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
    LocalCommandTrustContext,
    LocalCommandTrustManagementError,
)


def _local_command_trust_store_path() -> Path:
    """Return the fixed machine-local store path below SASE home."""
    return (
        sase_home()
        / LOCAL_COMMAND_TRUST_STORE_DIRECTORY
        / LOCAL_COMMAND_TRUST_STORE_FILENAME
    )


def _store_snapshot(identity: str) -> dict[str, Any]:
    binding = require_rust_binding("local_command_trust_store_get")
    result = binding(str(sase_home()), identity)
    _validate_store_wire(result)
    return result


def _validate_store_wire(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LocalCommandTrustManagementError(
            "Rust local-command trust store returned no mapping"
        )
    if payload.get("schema_version") != LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION:
        raise LocalCommandTrustManagementError(
            "unsupported local-command trust store wire version: "
            f"{payload.get('schema_version')!r}"
        )
    return payload


def store_allow(identity: str, digest: str) -> dict[str, Any]:
    audit_name = require_human_terminal()
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


def store_revoke(identity: str) -> dict[str, Any]:
    require_human_terminal()
    store_path = _local_command_trust_store_path()
    assert_test_state_write_isolated(
        store_path, category="local-command trust revocation"
    )
    binding = require_rust_binding("local_command_trust_store_revoke")
    result = binding(str(sase_home()), identity)
    return _validate_store_wire(result)


def status_payload(context: LocalCommandTrustContext) -> dict[str, Any]:
    try:
        from sase.config.local_trust_enforcement import (
            is_local_command_trust_enabled as _flag_enabled,
        )

        flag_enabled = _flag_enabled()
    except Exception:
        flag_enabled = True
    if not flag_enabled:
        return {
            "schema_version": LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION,
            "status": "compatibility",
            "project_identity": context.project_identity,
            "checkout_root": str(context.checkout_root),
            "selected_config_path": str(context.selected_config_path),
            "logical_config_path": context.logical_config_path,
            "current_digest": context.projection.digest,
            "acknowledged_digest": None,
            "policy_version": context.projection.policy_version,
            "acknowledged_policy_version": None,
            "blocked_paths": list(context.projection.blocked_paths),
            "reason": (
                "local_config_command_trust is off; local commands run in "
                "compatibility mode without acknowledgment"
            ),
            "flag": "local_config_command_trust",
            "flag_enabled": False,
        }
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


def status_local_commands(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return the current local-command trust status without mutating state."""
    return status_payload(resolve_local_command_trust_context(path))


def require_human_terminal() -> str:
    try:
        if agent_marker_present():
            raise LocalCommandTrustManagementError(
                "local command trust can only be changed by a human in a foreground terminal"
            )
    except LocalCommandTrustManagementError:
        raise
    except Exception as error:
        raise LocalCommandTrustManagementError(
            f"cannot determine agent or monitor identity; refusing trust mutation: {error}"
        ) from error

    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise LocalCommandTrustManagementError(
                "local command trust changes require an interactive terminal"
            )
        if hasattr(os, "tcgetpgrp"):
            foreground = os.tcgetpgrp(sys.stdin.fileno())
            if foreground != os.getpgrp():
                raise LocalCommandTrustManagementError(
                    "local command trust changes require the foreground terminal"
                )
        identity = resolve_audit_identity()
    except LocalCommandTrustManagementError:
        raise
    except Exception as error:
        raise LocalCommandTrustManagementError(
            f"cannot establish a human terminal identity; refusing trust mutation: {error}"
        ) from error
    if identity.source != "interactive":
        raise LocalCommandTrustManagementError(
            "local command trust changes require a human identity"
        )
    return identity.name


def require_local_trust_human_terminal() -> None:
    """Argparse-side actor guard; mutation adapters repeat it at write time."""
    require_human_terminal()


def local_trust_store_snapshot(identity: str) -> dict[str, Any]:
    """Return the machine-local trust store snapshot for *identity*.

    Public accessor for enforcement paths that must read the same store
    snapshot the acknowledgment CLI uses. Failures are returned as payloads
    by the Rust binding; callers fail closed for local execution.
    """
    return _store_snapshot(identity)
