"""Durable operational workspace leases for non-agent host work.

Acquisition claims the next unified-pool workspace, materializes its
checkout, prepares it from the configured primary remote, and exposes a
leased :class:`~sase.workspace_provider.ownership.OperationContext`.
Preparation failure, normal completion, and every exceptional exit
release the claim. Failures never fall back to the user-owned primary
checkout.

Claim allocation and transfer reuse the existing Rust RUNNING-field
plans. Workspace eligibility and settlement-policy shape match the
cross-frontend decisions in ``sase_core::workspace_lease``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace,
    operational_lease_claim_workflow,
    release_workspace,
    transfer_workspace_claim,
)
from sase.workspace_provider._lease_checkout import materialize_leased_checkout
from sase.workspace_provider._lease_git import prepare_from_primary_remote
from sase.workspace_provider._lease_model import (
    OPERATIONAL_LEASE_POLICY_KIND,
    OperationalLease,
    OperationalLeaseError,
    authorize_operational_lease_workspace,
    is_operational_lease_contention_error,
    is_operational_lease_policy,
)
from sase.workspace_provider.ownership import (
    leased_operational_context,
)
from sase.workspace_provider.reset_replay import (
    ReplayConflict,
    ReplayDeferred,
    ResetReplayError,
    ResetReplayResult,
)

_OperationalLeaseError = OperationalLeaseError
_authorize_operational_lease_workspace = authorize_operational_lease_workspace
_materialize_leased_checkout = materialize_leased_checkout
_prepare_from_primary_remote = prepare_from_primary_remote


def acquire_operational_lease(
    project: str,
    *,
    workflow: str,
    holder: str,
    project_file: str | Path | None = None,
    cl_name: str | None = None,
    pid: int | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> OperationalLease:
    """Claim, materialize, and prepare one operational workspace.

    On any failure after the RUNNING claim is taken, the claim is
    released. The primary checkout is never used as a fallback cwd.

    The RUNNING-field label is the reserved ``lease(<workflow>)`` form, which
    marks the claim as a machine-owned lease rather than an agent run.
    ``OperationalLease.workflow`` reports that on-disk label rather than the
    *workflow* argument; ``holder`` stays the caller's identity.
    """

    if not workflow or not workflow.strip():
        raise _OperationalLeaseError("allocation", "workflow identity is required")
    if not holder or not holder.strip():
        raise _OperationalLeaseError("allocation", "holder identity is required")

    spec = _resolve_project_file(project, project_file)
    claim_workflow = operational_lease_claim_workflow(workflow.strip())
    claim_name = cl_name if cl_name else holder
    claim_pid = os.getpid() if pid is None else pid
    workspace_num: int | None = None
    try:
        workspace_num = _claim_pool_workspace(
            spec,
            workflow=claim_workflow,
            pid=claim_pid,
            cl_name=claim_name,
        )
        checkout = _materialize_leased_checkout(
            spec,
            project,
            workspace_num,
            config=config,
            env=env,
        )
        _prepare_from_primary_remote(checkout)
        context = leased_operational_context(
            project,
            workspace_num,
            checkout_dir=checkout,
            project_file=spec,
            config=config,
            env=env,
        )
        if context.checkout_dir != checkout:
            raise _OperationalLeaseError(
                "materialization",
                f"leased context checkout {context.checkout_dir} "
                f"does not match {checkout}",
            )
        if context.is_primary:
            raise _OperationalLeaseError(
                "allocation",
                "leased operational context resolved to primary workspace #0",
            )
        return OperationalLease(
            project=project,
            workflow=claim_workflow,
            holder=holder,
            workspace_num=workspace_num,
            checkout_dir=checkout,
            project_file=spec,
            claim_pid=claim_pid,
            cl_name=claim_name,
            context=context,
        )
    except _OperationalLeaseError:
        _release_acquired_claim(spec, workspace_num, claim_workflow, claim_name)
        raise
    except Exception as exc:
        _release_acquired_claim(spec, workspace_num, claim_workflow, claim_name)
        raise _OperationalLeaseError("recovery", str(exc)) from exc


def release_operational_lease(
    lease: OperationalLease | Mapping[str, Any] | None,
) -> None:
    """Release a lease or persisted settlement policy. Idempotent."""

    if lease is None:
        return
    if isinstance(lease, OperationalLease):
        _release_claim(
            lease.project_file,
            lease.workspace_num,
            lease.workflow,
            lease.cl_name,
        )
        return
    if not is_operational_lease_policy(lease):
        return
    project_file = lease.get("project_file")
    workspace_num = lease.get("workspace_num")
    workflow = lease.get("workflow")
    if not isinstance(project_file, str) or workspace_num is None:
        return
    if not isinstance(workflow, str) or not workflow:
        return
    cl_name = lease.get("cl_name")
    _release_claim(
        project_file,
        int(workspace_num),
        workflow,
        cl_name if isinstance(cl_name, str) else None,
    )


def _bind_operational_lease(
    request: Any,
    lease: OperationalLease,
) -> Any:
    """Copy *request* onto the leased checkout and attach settlement policy."""

    from dataclasses import replace

    from sase.procs.request import ProcSubmitRequest

    if not isinstance(request, ProcSubmitRequest):
        raise _OperationalLeaseError(
            "allocation",
            "durable leased submission requires a ProcSubmitRequest",
        )
    return replace(
        request,
        cwd=str(lease.checkout_dir),
        project=request.project or lease.project,
        workspace_num=lease.workspace_num,
        cl_name=request.cl_name or lease.cl_name,
        workspace_claim=lease.settlement_policy(),
    )


def _transfer_operational_lease(lease: OperationalLease, proc: Any) -> None:
    """Hand the preclaim to the acknowledged supervisor PID."""

    supervisor_pid = _supervisor_pid(proc)
    if supervisor_pid is None:
        raise _OperationalLeaseError(
            "transfer",
            "acknowledged supervisor did not report a pid",
        )
    result = transfer_workspace_claim(
        str(lease.project_file),
        lease.workspace_num,
        from_pid=lease.claim_pid,
        to_pid=supervisor_pid,
        new_workflow=lease.workflow,
        new_artifacts_timestamp=None,
        cl_name=lease.cl_name,
    )
    if not result.success:
        raise _OperationalLeaseError(
            "transfer",
            result.error or "workspace claim transfer was rejected",
        )


def submit_via_lease(
    request: Any,
    lease: OperationalLease,
    *,
    after_ack: Callable[[Any], None] | None = None,
) -> Any:
    """Submit *request* inside an already-acquired *lease*, then transfer.

    The claim is released on a pre-transfer spawn error. After a successful
    transfer, proc settlement releases the claim exactly once. Use this when
    the caller already holds a lease it wants this submission
    to share -- for example a detached fallback that reuses the same lease a
    prior monitor-start attempt acquired.
    """

    from sase.procs.service import submit_proc_request

    transferred = False

    def _after_ack(proc: Any) -> None:
        nonlocal transferred
        _transfer_operational_lease(lease, proc)
        transferred = True
        if after_ack is not None:
            after_ack(proc)

    try:
        return submit_proc_request(
            _bind_operational_lease(request, lease),
            after_ack=_after_ack,
        )
    except Exception:
        if not transferred:
            release_operational_lease(lease)
        raise


@contextmanager
def operational_workspace_lease(
    project: str,
    *,
    workflow: str,
    holder: str,
    project_file: str | Path | None = None,
    cl_name: str | None = None,
    pid: int | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Iterator[OperationalLease]:
    """Synchronous lease for chops and in-process host actions."""

    lease = acquire_operational_lease(
        project,
        workflow=workflow,
        holder=holder,
        project_file=project_file,
        cl_name=cl_name,
        pid=pid,
        config=config,
        env=env,
    )
    try:
        yield lease
    finally:
        release_operational_lease(lease)


def _resolve_project_file(
    project: str,
    project_file: str | Path | None,
) -> Path:
    if project_file is not None:
        path = Path(project_file)
        if not path.is_file():
            raise _OperationalLeaseError(
                "allocation",
                f"project file does not exist: {path}",
            )
        return path.expanduser().resolve(strict=False)
    if not project:
        raise _OperationalLeaseError("allocation", "project identity is required")
    from sase.workflows.utils import get_project_file_path

    path = Path(get_project_file_path(project))
    if not path.is_file():
        raise _OperationalLeaseError(
            "allocation",
            f"project file does not exist: {path}",
        )
    return path.expanduser().resolve(strict=False)


def _claim_pool_workspace(
    project_file: Path,
    *,
    workflow: str,
    pid: int,
    cl_name: str | None,
) -> int:
    try:
        workspace_num = claim_next_axe_workspace(
            str(project_file),
            workflow,
            pid,
            cl_name=cl_name,
        )
    except WorkspaceClaimError as exc:
        raise _OperationalLeaseError("allocation", str(exc)) from exc
    return _authorize_operational_lease_workspace(workspace_num)


def _release_acquired_claim(
    project_file: Path,
    workspace_num: int | None,
    workflow: str,
    cl_name: str | None,
) -> None:
    if workspace_num is None:
        return
    try:
        _authorize_operational_lease_workspace(workspace_num)
    except _OperationalLeaseError:
        return
    _release_claim(project_file, workspace_num, workflow, cl_name)


def _release_claim(
    project_file: str | Path,
    workspace_num: int,
    workflow: str,
    cl_name: str | None,
) -> None:
    release_workspace(
        str(project_file),
        workspace_num,
        workflow,
        cl_name=cl_name,
    )


def _supervisor_pid(proc: Any) -> int | None:
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int) and pid > 0:
        return pid
    proc_id = getattr(proc, "proc_id", None)
    if not isinstance(proc_id, str) or not proc_id:
        return None
    from sase.procs.runtime import proc_started_path, read_json_object

    started = read_json_object(proc_started_path(proc_id))
    raw = started.get("pid")
    return raw if isinstance(raw, int) and raw > 0 else None


__all__ = [
    "OPERATIONAL_LEASE_POLICY_KIND",
    "OperationalLease",
    "OperationalLeaseError",
    "ReplayConflict",
    "ReplayDeferred",
    "ResetReplayError",
    "ResetReplayResult",
    "acquire_operational_lease",
    "is_operational_lease_policy",
    "is_operational_lease_contention_error",
    "operational_workspace_lease",
    "release_operational_lease",
    "submit_via_lease",
]
