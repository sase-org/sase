"""Checkout materialization helpers for operational workspace leases."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.workspace_provider._lease_model import (
    OperationalLeaseError,
    authorize_operational_lease_workspace,
)
from sase.workspace_provider.marker import write_marker
from sase.workspace_provider.registry import record_workspace
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import ensure_workspace_checkout, parse_workspace_dir


def materialize_leased_checkout(
    project_file: Path,
    project: str,
    workspace_num: int,
    *,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> Path:
    authorize_operational_lease_workspace(workspace_num)
    primary = parse_workspace_dir(str(project_file))
    if not primary:
        raise OperationalLeaseError(
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
        raise OperationalLeaseError("materialization", str(exc)) from exc
    checkout_path = Path(checkout).expanduser().resolve(strict=False)
    if checkout_path == Path(primary_dir):
        raise OperationalLeaseError(
            "materialization",
            "materialization resolved to the primary checkout; "
            "refusing to lease user-owned workspace #0",
        )
    store = WorkspaceStore(primary_dir, config=config, env=env)
    workspace_path = store.resolve(workspace_num)
    expected = Path(workspace_path.checkout_dir).expanduser().resolve(strict=False)
    if checkout_path != expected:
        raise OperationalLeaseError(
            "materialization",
            f"checkout {checkout_path} does not match store path {expected}",
        )
    try:
        record_workspace(store, workspace_path)
        marker = write_marker(store, workspace_path)
    except Exception as exc:
        raise OperationalLeaseError("materialization", str(exc)) from exc
    if marker is None:
        raise OperationalLeaseError(
            "materialization",
            f"could not write a checkout marker for workspace #{workspace_num}",
        )
    return checkout_path


__all__ = ["materialize_leased_checkout"]
