"""Resolve and spawn a successor on the held recovery workspace."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack._recovery_successor_common import (
    RECOVERY_LINEAGE_ENV,
    RECOVERY_DESCRIPTOR_ENV,
    RECOVERY_STRICT_ENV,
    RecoveryInheritanceError,
    RecoveryLineage,
    encode_recovery_lineage,
    normalize_recovery_lineage,
)
from sase.agent.hijack._recovery_successor_descriptor import encode_recovery_descriptor


def _recovery_child_env(lineage: RecoveryLineage | Mapping[str, Any]) -> dict[str, str]:
    """Return the environment delta a recovery successor boots with."""
    return {
        RECOVERY_LINEAGE_ENV: encode_recovery_lineage(lineage),
        RECOVERY_STRICT_ENV: "1",
    }


def _validate_recovery_workspace_pair(
    *,
    project_name: str,
    workspace_num: object,
    workspace_dir: object,
) -> None:
    """Require the exact positive workspace pair, raising on any deviation.

    Foreign owners, workspace ``#0``, pool workspaces, and metadata where the
    number and directory disagree are all rejected here, before spawn.
    """
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        raise RecoveryInheritanceError(
            "recovery requires the held positive workspace number, "
            f"got {workspace_num!r}"
        )
    if not isinstance(workspace_dir, str) or not workspace_dir.strip():
        raise RecoveryInheritanceError(
            f"recovery requires the held workspace directory, got {workspace_dir!r}"
        )
    try:
        from sase.running_field import get_workspace_directory_for_num
    except ImportError:
        return
    try:
        canonical_dir, _ = get_workspace_directory_for_num(
            workspace_num,
            project_name,
            clean=False,
        )
    except (RuntimeError, OSError, ValueError):
        return
    if os.path.normpath(canonical_dir) != os.path.normpath(workspace_dir):
        raise RecoveryInheritanceError(
            f"recovery workspace metadata mismatch: workspace #{workspace_num} "
            f"resolves to {canonical_dir}, not {workspace_dir}"
        )


def prepare_recovery_successor(
    directive: Any,
    *,
    project_name: str,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage | Mapping[str, Any],
    descriptor: Mapping[str, Any] | None = None,
    resolve_plan: Any | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[Any, dict[str, str]]:
    """Resolve the exact reserved session member for a recovery successor.

    The shared agent-session attach resolver performs the resolution, so a
    solo-agent predecessor is promoted exactly as a normal follow-up would
    be. The workspace pair is validated before resolution; any deviation
    raises :class:`RecoveryInheritanceError`. Returns the resolved plan and
    the child environment delta (lineage, the strict-boot marker, and the
    reservation descriptor when one was bound). The child boot decodes the
    descriptor before provider execution and fails closed when it is
    missing.
    """
    resolved_lineage = normalize_recovery_lineage(lineage)
    _validate_recovery_workspace_pair(
        project_name=project_name,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
    )
    from sase.agent import _agent_session_attach_resolution as _resolution

    resolve = resolve_plan or _resolution.resolve_agent_session_attach_plan
    plan = resolve(directive, project_name=project_name)
    if not plan.predecessor_artifacts_dir:
        from dataclasses import replace
        from sase.agent.hijack import ledger

        record = ledger.load_record(resolved_lineage.hijack_id)
        predecessor_dir = record.get("artifacts_dir") if record is not None else None
        if not predecessor_dir and plan.parent_name == resolved_lineage.predecessor:
            predecessor_dir = plan.parent_artifacts_dir
        plan = replace(
            plan,
            predecessor_artifacts_dir=predecessor_dir,
            predecessor_name=resolved_lineage.predecessor,
        )
    env: dict[str, str] = _recovery_child_env(resolved_lineage)
    if descriptor is not None:
        env[RECOVERY_DESCRIPTOR_ENV] = encode_recovery_descriptor(descriptor)
    if extra_env:
        env.update(dict(extra_env))
    return plan, env


def spawn_recovery_successor(
    directive: Any,
    *,
    project_name: str,
    project_file: str | None = None,
    prompt: str,
    workspace_dir: str,
    workspace_num: int,
    transfer_from_pid: int | None,
    lineage: RecoveryLineage | Mapping[str, Any],
    descriptor: Mapping[str, Any] | None = None,
    cl_name: str | None = None,
    agent_session_role: str | None = None,
    vcs_ref: tuple[str, str] | None = None,
    timestamp: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    spawn_fn: Any | None = None,
    resolve_plan: Any | None = None,
) -> Any:
    """Spawn a recovery successor on the exact held workspace pair.

    A narrow seam over
    :func:`sase.agent.detached_child.spawn_agent_session_successor`: one
    resolution (reused for the spawn so the reserved member cannot drift),
    one transfer-or-fresh-claim on the same pair, no pool or ``#0``
    fallback. Workspace or lineage validation failures raise
    :class:`RecoveryInheritanceError` before any spawn is attempted. A
    reservation descriptor threads into the child environment so its boot
    can prove inheritance before provider execution.
    """
    from sase.agent.detached_child import spawn_agent_session_successor

    plan, prepared_env = prepare_recovery_successor(
        directive,
        project_name=project_name,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        transfer_from_pid=transfer_from_pid,
        lineage=lineage,
        descriptor=descriptor,
        resolve_plan=resolve_plan,
        extra_env=extra_env,
    )
    merged_env = dict(prepared_env)
    if extra_env:
        merged_env.update(dict(extra_env))
    return spawn_agent_session_successor(
        directive,
        project_name=project_name,
        project_file=project_file,
        prompt=prompt,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        transfer_from_pid=transfer_from_pid,
        cl_name=cl_name or plan.agent_name,
        agent_session_role=agent_session_role,
        vcs_ref=vcs_ref,
        timestamp=timestamp,
        extra_env=merged_env,
        spawn_fn=spawn_fn,
        resolve_plan=lambda *args, **kwargs: plan,
    )
