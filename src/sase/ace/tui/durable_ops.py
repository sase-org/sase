"""Canonical argv, fingerprints, and concurrency keys for ACE durable producers."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any

from sase.ace.patch.project_spec_path import project_spec_basename
from sase.procs.service import ProcSubmitError

# Payload keys that must never enter argv, labels, logs, or raw fingerprints.
_SENSITIVE_FINGERPRINT_KEYS = frozenset(
    {
        "description",
        "prompt",
        "entries",
        "shas",
        "accepted_entries",
        "value",
    }
)
_VOLATILE_FINGERPRINT_KEYS = frozenset(
    {
        "result_path",
        "request_path",
        "workspace_dir",
        "cwd",
    }
)


def sase_command_argv(*parts: str) -> list[str]:
    """Return canonical ``python -m sase …`` argv for a durable submission."""
    argv = [sys.executable, "-m", "sase"]
    argv.extend(str(part) for part in parts if part)
    return argv


def project_identity(project_file: str) -> str:
    """Return the stable project-spec identity used in concurrency keys."""
    return project_spec_basename(project_file)


def patch_concurrency_key(project_file: str, name: str) -> str:
    """Return the shared-store key for all mutations of one Patch."""
    return f"ace:patch:{project_identity(project_file)}:{name}"


def agent_directive_concurrency_key(artifacts_dir: str) -> str:
    """Return the shared-store key for one agent's metadata mutations."""
    return f"ace:agent-directive:{_normalized_identity(artifacts_dir)}"


def agent_tribe_concurrency_key() -> str:
    """Return the shared-store key for tribe-store mutations."""
    return "ace:agent-directive:tribes"


def launch_concurrency_key(workflow: str) -> str:
    """Return the shared-store key for one launch identity."""
    return f"ace:launch:{workflow}"


def cleanup_concurrency_key(proc_type: str, identity: str) -> str:
    """Return the shared-store key for one cleanup/dismiss/kill claim."""
    return f"ace:cleanup:{proc_type}:{_normalized_identity(identity)}"


def revert_concurrency_key(prefix: str, *parts: str) -> str:
    """Return the shared-store key for one agent-revert execution."""
    return ":".join(("ace:agent-revert", prefix, *parts))


def workspace_claim_policy(
    *,
    project_file: str,
    workspace_num: int,
    workflow: str,
    cl_name: str,
) -> dict[str, Any]:
    """Return the settlement policy that releases a workspace claim once."""
    return {
        "cl_name": cl_name,
        "project_file": project_file,
        "workflow": workflow,
        "workspace_num": int(workspace_num),
    }


def operation_fingerprint(
    operation: str,
    identifiers: Mapping[str, Any],
) -> str:
    """Return a stable fingerprint that excludes volatile and sensitive values.

    Sensitive payload values are hashed so replay stays idempotent without
    putting descriptions, prompts, or SHAs into the fingerprint material.
    """
    material: dict[str, Any] = {"operation": operation}
    for key, value in identifiers.items():
        if key in _VOLATILE_FINGERPRINT_KEYS:
            continue
        if key in _SENSITIVE_FINGERPRINT_KEYS:
            material[f"{key}_digest"] = _digest_value(value)
        else:
            material[key] = value
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def is_concurrency_collision(exc: BaseException) -> bool:
    """Return True when *exc* is an atomic shared-store concurrency collision."""
    if not isinstance(exc, ProcSubmitError):
        return False
    message = str(exc).lower()
    return "concurrency" in message


def release_workspace_claim(policy: Mapping[str, Any] | None) -> None:
    """Release a workspace claim when no reserved proc can settle it."""
    if not policy:
        return
    project_file = policy.get("project_file")
    workspace_num = policy.get("workspace_num")
    if not isinstance(project_file, str) or workspace_num is None:
        return
    from sase.running_field import release_workspace

    release_workspace(
        project_file,
        int(workspace_num),
        workflow=policy.get("workflow")
        if isinstance(policy.get("workflow"), str)
        else None,
        cl_name=policy.get("cl_name")
        if isinstance(policy.get("cl_name"), str)
        else None,
    )


def _normalized_identity(value: str) -> str:
    path = Path(value).expanduser()
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _digest_value(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = [
    "agent_directive_concurrency_key",
    "agent_tribe_concurrency_key",
    "cleanup_concurrency_key",
    "is_concurrency_collision",
    "launch_concurrency_key",
    "operation_fingerprint",
    "patch_concurrency_key",
    "project_identity",
    "release_workspace_claim",
    "revert_concurrency_key",
    "sase_command_argv",
    "workspace_claim_policy",
]
