"""Data model and validation helpers for operational workspace leases."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.workspace_provider.ownership import (
    MACHINE_OWNED_MIN_WORKSPACE,
    OperationContext,
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
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

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


class OperationalLeaseError(RuntimeError):
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


_OperationalLeaseError = OperationalLeaseError


def is_operational_lease_contention_error(exc: BaseException) -> bool:
    """Return whether *exc* represents a retryable busy workspace pool."""

    if not isinstance(exc, OperationalLeaseError) or exc.step != "allocation":
        return False
    text = f"{exc.detail} {exc}".lower()
    if "workspace" not in text:
        return False
    return any(
        token in text
        for token in (
            "already claimed",
            "all axe workspaces",
            "all workspaces",
            "busy",
            "claimed",
            "no available",
            "unavailable",
            "exhausted",
        )
    )


@dataclass(frozen=True)
class OperationalLease:
    """One claimed, materialized, machine-owned operational checkout.

    ``workflow`` is the reserved ``lease(<workflow>)`` label as written to the
    RUNNING field, so settlement, transfer, and release all match what is on
    disk. ``holder`` remains the caller's own identity.
    """

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


def authorize_operational_lease_workspace(workspace_num: int) -> int:
    """Accept a unified-pool workspace number for a machine-owned lease."""

    normalized = normalize_workspace_num(workspace_num)
    if normalized == PRIMARY_WORKSPACE_NUM:
        raise OperationalLeaseError(
            "allocation",
            "cannot lease primary workspace #0 "
            "(legacy #1 normalizes to the user-owned primary checkout)",
        )
    if normalized < MACHINE_OWNED_MIN_WORKSPACE:
        raise OperationalLeaseError(
            "allocation",
            f"cannot lease reserved workspace #{normalized}; "
            f"machine-owned leases start at #{MACHINE_OWNED_MIN_WORKSPACE}",
        )
    if normalized > _UNIFIED_MAX_WORKSPACE:
        raise OperationalLeaseError(
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


__all__ = [
    "OPERATIONAL_LEASE_POLICY_KIND",
    "OperationalLease",
    "OperationalLeaseError",
    "ReplayConflict",
    "ReplayDeferred",
    "ResetReplayError",
    "ResetReplayResult",
    "authorize_operational_lease_workspace",
    "is_operational_lease_contention_error",
    "is_operational_lease_policy",
]
