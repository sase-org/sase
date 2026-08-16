"""Shared operational-lease test doubles for approval-time host actions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
)


def fake_operational_lease(
    checkout: Path,
    *,
    project: str = "demo",
    workflow: str = "test",
    holder: str = "test",
    workspace_num: int = 10,
    claim_pid: int = 4321,
    primary_checkout: Path | None = None,
) -> OperationalLease:
    """Return an :class:`OperationalLease` whose checkout is *checkout*."""
    primary = primary_checkout or checkout
    context = OperationContext(
        project=project,
        access_kind=AccessKind.LEASED_OPERATIONAL,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=primary,
        claim_pid=claim_pid,
        claim_workflow=workflow,
    )
    return OperationalLease(
        project=project,
        workflow=workflow,
        holder=holder,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        project_file=checkout / f"{project}.sase",
        claim_pid=claim_pid,
        cl_name=None,
        context=context,
    )


def patched_operational_lease(
    checkout: Path,
    *,
    primary_checkout: Path | None = None,
    seen: list[tuple[str, str]] | None = None,
) -> Any:
    """Patch target for ``operational_workspace_lease`` that reuses *checkout*.

    When *seen* is given, each call's ``(project, workflow)`` is appended to
    it, mirroring how production code resolves a project before leasing it.
    """

    @contextmanager
    def _lease_cm(
        project: str, *, workflow: str, **_kwargs: object
    ) -> Iterator[OperationalLease]:
        if seen is not None:
            seen.append((project, workflow))
        yield fake_operational_lease(
            checkout,
            project=project,
            workflow=workflow,
            primary_checkout=primary_checkout,
        )

    return patch(
        "sase.workspace_provider.lease.operational_workspace_lease",
        _lease_cm,
    )
