"""Temporary workspace leases for project-scoped launch conditions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.monitor.transaction import write_json_marker_atomic
from sase.workspace_provider.lease import (
    OperationalLease,
    OperationalLeaseError,
    acquire_operational_lease,
    is_operational_lease_contention_error,
    release_operational_lease,
)

CONDITION_WORKSPACE_MARKER = "condition_workspace_lease.json"
CONDITION_WORKSPACE_MARKER_SCHEMA_VERSION = 1


class ConditionWorkspaceUnavailable(RuntimeError):
    """Raised when the workspace pool is busy and admission should retry."""


class ConditionWorkspaceError(RuntimeError):
    """Raised when a condition workspace lease failed closed."""


@dataclass(frozen=True)
class _ConditionWorkspaceLease:
    """A prepared checkout held only for one condition evaluation."""

    logical_id: str
    request_id: str
    work_dir: Path
    lease: OperationalLease

    @property
    def checkout_dir(self) -> Path:
        return self.lease.checkout_dir

    def context_payload(self) -> dict[str, Any]:
        """Return condition-context additions for the evaluator."""

        return {
            "condition_workspace_cwd": str(self.lease.checkout_dir),
            "condition_workspace_num": self.lease.workspace_num,
            "condition_workspace_workflow": self.lease.workflow,
            "condition_workspace_claim": self.lease.settlement_policy(),
        }


def acquire_condition_workspace(
    *,
    project: str,
    request_id: str,
    plan_digest: str,
    logical_id: str,
    work_dir: str | Path,
    project_file: str | Path | None = None,
) -> _ConditionWorkspaceLease:
    """Acquire a prepared numbered checkout for one project-scoped condition."""

    root = Path(work_dir)
    settle_condition_workspace(root)
    workflow = _condition_workspace_workflow(
        request_id=request_id,
        plan_digest=plan_digest,
        logical_id=logical_id,
    )
    try:
        lease = acquire_operational_lease(
            project,
            workflow=workflow,
            holder=workflow,
            project_file=project_file,
            cl_name=workflow,
            pid=os.getpid(),
        )
    except OperationalLeaseError as exc:
        if is_operational_lease_contention_error(exc):
            raise ConditionWorkspaceUnavailable(str(exc)) from exc
        raise ConditionWorkspaceError(str(exc)) from exc
    marker = _marker_payload(
        lease,
        request_id=request_id,
        plan_digest=plan_digest,
        logical_id=logical_id,
        settled=False,
    )
    try:
        write_json_marker_atomic(_marker_path(root), marker)
    except Exception as exc:
        policy = lease.settlement_policy()
        try:
            release_operational_lease(policy)
        except Exception as release_exc:
            raise ConditionWorkspaceError(
                "condition workspace marker persistence failed after lease "
                f"acquisition; release failed: {release_exc}"
            ) from exc
        raise ConditionWorkspaceError(
            "condition workspace marker persistence failed after lease "
            f"acquisition: {exc}"
        ) from exc
    return _ConditionWorkspaceLease(
        logical_id=logical_id,
        request_id=request_id,
        work_dir=root,
        lease=lease,
    )


def settle_condition_workspace(work_dir: str | Path) -> None:
    """Release the persisted condition lease for *work_dir*, if any."""

    root = Path(work_dir)
    marker_path = _marker_path(root)
    marker = _read_marker(marker_path)
    if marker is None or bool(marker.get("settled")):
        return
    policy = marker.get("lease")
    if isinstance(policy, dict):
        release_operational_lease(policy)
    marker["settled"] = True
    marker["settled_at_unix"] = time.time()
    write_json_marker_atomic(marker_path, marker)


def _condition_workspace_workflow(
    *,
    request_id: str,
    plan_digest: str,
    logical_id: str,
) -> str:
    """Return a stable lease workflow for one request/logical condition."""

    key = f"{request_id}\0{plan_digest}\0{logical_id}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    request = _slug(request_id or "request")[:24]
    logical = _slug(logical_id or "unit")[:24]
    return f"launch-if:{request}:{logical}:{digest}"


def _marker_payload(
    lease: OperationalLease,
    *,
    request_id: str,
    plan_digest: str,
    logical_id: str,
    settled: bool,
) -> dict[str, Any]:
    return {
        "schema_version": CONDITION_WORKSPACE_MARKER_SCHEMA_VERSION,
        "logical_id": logical_id,
        "request_id": request_id,
        "plan_digest": plan_digest,
        "project": lease.project,
        "checkout_dir": str(lease.checkout_dir),
        "workspace_num": lease.workspace_num,
        "lease": lease.settlement_policy(),
        "settled": settled,
        "updated_at_unix": time.time(),
    }


def _marker_path(work_dir: Path) -> Path:
    return work_dir / CONDITION_WORKSPACE_MARKER


def _read_marker(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


_SLUG_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


def _slug(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip()).strip("-")
    return slug or "condition"


__all__ = [
    "CONDITION_WORKSPACE_MARKER",
    "ConditionWorkspaceError",
    "ConditionWorkspaceUnavailable",
    "acquire_condition_workspace",
    "settle_condition_workspace",
]
