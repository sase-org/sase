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
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace,
    release_workspace,
    transfer_workspace_claim,
)
from sase.workspace_provider.marker import write_marker
from sase.workspace_provider.ownership import (
    MACHINE_OWNED_MIN_WORKSPACE,
    OperationContext,
    leased_operational_context,
    normalize_workspace_num,
)
from sase.workspace_provider.reset_replay import (
    DEFAULT_MAX_ATTEMPTS,
    ReplayConflict,
    ReplayDeferred,
    ResetReplayError,
    ResetReplayResult,
    reset_and_replay as run_reset_and_replay,
    reset_leased_checkout_to_upstream,
)
from sase.workspace_provider.registry import record_workspace
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM, WorkspaceStore
from sase.workspace_provider.utils import (
    ensure_workspace_checkout,
    get_default_branch,
    non_interactive_git_env,
    parse_workspace_dir,
)

OPERATIONAL_LEASE_POLICY_KIND = "operational_lease"
_UNIFIED_MAX_WORKSPACE = 999

_LEASE_FAILURE_KINDS = frozenset(
    {
        "allocation",
        "materialization",
        "preparation",
        "transfer",
        "recovery",
    }
)


class _OperationalLeaseError(RuntimeError):
    """Resumable failure of one operational-lease step.

    The message names the failed operation and never authorizes using the
    user's primary checkout.
    """

    def __init__(
        self,
        operation: str,
        detail: str,
        *,
        step: str | None = None,
        resumable: bool = True,
    ) -> None:
        kind = step if step in _LEASE_FAILURE_KINDS else operation
        if kind not in _LEASE_FAILURE_KINDS:
            kind = "allocation"
        if operation in _LEASE_FAILURE_KINDS:
            named = operation
        else:
            named = f"{kind} of {operation}"
        message = (
            f"operational workspace lease failed during {named}: {detail}; "
            "the user-owned primary checkout was left untouched"
        )
        super().__init__(message)
        self.operation = named
        self.detail = detail
        self.step = kind
        self.resumable = resumable


@dataclass(frozen=True)
class OperationalLease:
    """One claimed, materialized, machine-owned operational checkout."""

    project: str
    workflow: str
    holder: str
    workspace_num: int
    checkout_dir: Path
    project_file: Path
    claim_pid: int
    cl_name: str | None
    context: OperationContext

    @property
    def operation_context(self) -> OperationContext:
        """Leased operational context for writable store resolution."""

        return self.context

    def settlement_policy(self) -> dict[str, Any]:
        """Return the persisted policy that releases this lease once."""

        return _operational_lease_settlement_policy(self)

    def reset_and_replay(
        self,
        operation: Callable[[], Any],
        *,
        repo_root: str | Path | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        clear_paths: Sequence[str | Path] = (),
        clock: Callable[[], float] | None = None,
    ) -> ResetReplayResult:
        """Reset and replay *operation* inside this lease's checkout.

        Destructive recovery is authorized only for this lease's live
        operational context. Callers raise :class:`ReplayConflict` or
        :class:`ReplayDeferred` from *operation*; see
        :func:`sase.workspace_provider.reset_replay.reset_and_replay`.
        """

        return run_reset_and_replay(
            self.context,
            self.checkout_dir if repo_root is None else repo_root,
            operation,
            max_attempts=max_attempts,
            clear_paths=clear_paths,
            clock=clock,
        )

    def reset_to_upstream(
        self,
        *,
        repo_root: str | Path | None = None,
        clock: Callable[[], float] | None = None,
    ) -> str | None:
        """Hard-reset one repository inside this lease to its upstream tip.

        Defaults to the leased checkout. Pass a nested store clone — for
        example ``<checkout>/sase/repos/plans`` — to reset that repository
        instead. Authorization is the same as :meth:`reset_and_replay`.
        """

        return reset_leased_checkout_to_upstream(
            self.context,
            self.checkout_dir if repo_root is None else repo_root,
            clock=clock,
        )


def _authorize_operational_lease_workspace(workspace_num: int) -> int:
    """Accept a unified-pool workspace number for a machine-owned lease."""

    normalized = normalize_workspace_num(workspace_num)
    if normalized == PRIMARY_WORKSPACE_NUM:
        raise _OperationalLeaseError(
            "allocation",
            "cannot lease primary workspace #0 "
            "(legacy #1 normalizes to the user-owned primary checkout)",
        )
    if normalized < MACHINE_OWNED_MIN_WORKSPACE:
        raise _OperationalLeaseError(
            "allocation",
            f"cannot lease reserved workspace #{normalized}; "
            f"machine-owned leases start at #{MACHINE_OWNED_MIN_WORKSPACE}",
        )
    if normalized > _UNIFIED_MAX_WORKSPACE:
        raise _OperationalLeaseError(
            "allocation",
            f"cannot lease workspace #{normalized}; "
            f"the unified claim pool ends at #{_UNIFIED_MAX_WORKSPACE}",
        )
    return normalized


def is_operational_lease_policy(policy: Mapping[str, Any] | None) -> bool:
    """Return whether *policy* is a persisted operational-lease settlement."""

    return (
        isinstance(policy, Mapping)
        and policy.get("kind") == OPERATIONAL_LEASE_POLICY_KIND
    )


def _operational_lease_settlement_policy(
    lease: OperationalLease,
) -> dict[str, Any]:
    """Return the durable settlement policy for *lease*."""

    return {
        "cl_name": lease.cl_name,
        "holder": lease.holder,
        "kind": OPERATIONAL_LEASE_POLICY_KIND,
        "project_file": str(lease.project_file),
        "workflow": lease.workflow,
        "workspace_num": lease.workspace_num,
    }


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
    """

    if not workflow or not workflow.strip():
        raise _OperationalLeaseError("allocation", "workflow identity is required")
    if not holder or not holder.strip():
        raise _OperationalLeaseError("allocation", "holder identity is required")

    spec = _resolve_project_file(project, project_file)
    claim_name = cl_name if cl_name else holder
    claim_pid = os.getpid() if pid is None else pid
    workspace_num: int | None = None
    try:
        workspace_num = _claim_pool_workspace(
            spec,
            workflow=workflow,
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
            workflow=workflow,
            holder=holder,
            workspace_num=workspace_num,
            checkout_dir=checkout,
            project_file=spec,
            claim_pid=claim_pid,
            cl_name=claim_name,
            context=context,
        )
    except _OperationalLeaseError:
        _release_acquired_claim(spec, workspace_num, workflow, claim_name)
        raise
    except Exception as exc:
        _release_acquired_claim(spec, workspace_num, workflow, claim_name)
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


def _materialize_leased_checkout(
    project_file: Path,
    project: str,
    workspace_num: int,
    *,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> Path:
    _authorize_operational_lease_workspace(workspace_num)
    primary = parse_workspace_dir(str(project_file))
    if not primary:
        raise _OperationalLeaseError(
            "materialization",
            f"project {project!r} has no WORKSPACE_DIR; "
            "refusing to invent a primary checkout path",
        )
    primary_dir = str(Path(primary).expanduser().resolve(strict=False))
    try:
        checkout = ensure_workspace_checkout(
            primary_dir,
            workspace_num,
            config=config,
            env=env,
        )
    except Exception as exc:
        raise _OperationalLeaseError("materialization", str(exc)) from exc
    checkout_path = Path(checkout).expanduser().resolve(strict=False)
    if checkout_path == Path(primary_dir):
        raise _OperationalLeaseError(
            "materialization",
            "materialization resolved to the primary checkout; "
            "refusing to lease user-owned workspace #0",
        )
    store = WorkspaceStore(primary_dir, config=config, env=env)
    workspace_path = store.resolve(workspace_num)
    expected = Path(workspace_path.checkout_dir).expanduser().resolve(strict=False)
    if checkout_path != expected:
        raise _OperationalLeaseError(
            "materialization",
            f"checkout {checkout_path} does not match store path {expected}",
        )
    try:
        record_workspace(store, workspace_path)
        marker = write_marker(store, workspace_path)
    except Exception as exc:
        raise _OperationalLeaseError("materialization", str(exc)) from exc
    if marker is None:
        raise _OperationalLeaseError(
            "materialization",
            f"could not write a checkout marker for workspace #{workspace_num}",
        )
    return checkout_path


def _prepare_from_primary_remote(checkout: Path) -> None:
    if not (checkout / ".git").exists() and not (checkout / ".git").is_file():
        raise _OperationalLeaseError(
            "preparation",
            f"{checkout} is not a git checkout",
        )
    remotes = _git_remotes(checkout)
    if "origin" in remotes:
        fetch = _run_git(["fetch", "--quiet", "origin"], checkout)
        if fetch.returncode != 0:
            detail = fetch.stderr.strip() or fetch.stdout.strip() or "git fetch failed"
            raise _OperationalLeaseError("preparation", detail)
    upstream = _configured_upstream(checkout)
    if upstream is None:
        return
    local_branch = upstream.rsplit("/", 1)[-1]
    checkout_result = _run_git(
        ["checkout", "--force", "-B", local_branch, upstream],
        checkout,
    )
    if checkout_result.returncode != 0:
        detail = (
            checkout_result.stderr.strip()
            or checkout_result.stdout.strip()
            or f"git checkout {upstream} failed"
        )
        raise _OperationalLeaseError("preparation", detail)


def _configured_upstream(checkout: Path) -> str | None:
    tracking = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        checkout,
    )
    if tracking.returncode == 0:
        ref = tracking.stdout.strip()
        if ref:
            return ref
    origin_head = _run_git(
        ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
        checkout,
    )
    if origin_head.returncode == 0:
        ref = origin_head.stdout.strip()
        if ref.startswith("refs/remotes/"):
            return ref.removeprefix("refs/remotes/")
        if ref:
            return ref
    default_branch = get_default_branch(str(checkout))
    if _ref_exists(checkout, f"refs/remotes/{default_branch}"):
        return default_branch
    return None


def _git_remotes(checkout: Path) -> set[str]:
    result = _run_git(["remote"], checkout)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _ref_exists(checkout: Path, ref: str) -> bool:
    result = _run_git(["show-ref", "--verify", "--quiet", ref], checkout)
    return result.returncode == 0


def _run_git(args: list[str], checkout: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )


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
    "ReplayConflict",
    "ReplayDeferred",
    "ResetReplayError",
    "ResetReplayResult",
    "acquire_operational_lease",
    "is_operational_lease_policy",
    "operational_workspace_lease",
    "release_operational_lease",
    "submit_via_lease",
]
